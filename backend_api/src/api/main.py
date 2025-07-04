import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uuid
import time

import firebase_admin
from firebase_admin import credentials, auth, firestore, storage

# --- FIREBASE INIT ---

# PUBLIC_INTERFACE
def initialize_firebase():
    """Initializes Firebase app using the supplied config values."""
    if not firebase_admin._apps:
        cred = credentials.ApplicationDefault()
        # Setup environment variables for firebase_admin to allow Google Application Default Credentials.
        project_id = "doodlefinder"
        storage_bucket = "doodlefinder.firebasestorage.app"
        firebase_admin.initialize_app(
            cred,
            {'projectId': project_id, 'storageBucket': storage_bucket}
        )

initialize_firebase()

db = firestore.client()
bucket = storage.bucket()

# --- MODELS ---

class LoginRequest(BaseModel):
    username: str = Field(..., description="Desired username")


class LoginResponse(BaseModel):
    uid: str
    username: str
    token: str


class DrawingMetadata(BaseModel):
    drawing_id: str
    prompt: str
    creator_uid: str
    created_at: float
    image_url: str
    correct_guess_count: int
    guesses: List[str]
    wrong_guesses: List[str]
    highlighted: bool


class DrawingCreateRequest(BaseModel):
    prompt: str = Field(..., description="Randomly selected animal prompt")
    # Drawing data is uploaded as form-data image file


class GuessRequest(BaseModel):
    drawing_id: str
    guess: str


class GuessResponse(BaseModel):
    status: str
    correct: bool
    message: str
    correct_guess_count: int
    wrong_guesses: List[str]


class LeaderboardEntry(BaseModel):
    username: str
    correct_guesses: int
    drawings_created: int


class LeaderboardResponse(BaseModel):
    leaderboard: List[LeaderboardEntry]


# --- UTILITY FUNCS ---

ANIMALS = [
    "cat", "dog", "elephant", "lion", "tiger", "bear", "monkey", "giraffe", "koala", "kangaroo",
    "rabbit", "fox", "penguin", "horse", "zebra", "frog", "sheep", "panda", "hippo", "rhino"
]

def get_random_prompt() -> str:
    import random
    return random.choice(ANIMALS)

def get_timestamp():
    return time.time()

def get_uid_from_token(token: str) -> str:
    """Validate Firebase token and extract UID. Raises HTTPException on failure."""
    try:
        decoded = auth.verify_id_token(token)
        return decoded['uid']
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def drawing_doc_to_metadata(doc) -> DrawingMetadata:
    d = doc.to_dict()
    return DrawingMetadata(
        drawing_id=doc.id,
        prompt=d["prompt"],
        creator_uid=d["creator_uid"],
        created_at=d.get("created_at", 0),
        image_url=d["image_url"],
        correct_guess_count=len(set(d.get("correct_guessers", []))),
        guesses=list(set(d.get("guesses", []))),
        wrong_guesses=list(set(d.get("wrong_guesses", []))),
        highlighted=d.get("highlighted", False),
    )

def leaderboard_sort(entry):
    """Sort function for leaderboard: by correct guesses desc, then drawings created desc."""
    return (-entry.get("correct_guesses", 0), -entry.get("drawings_created", 0))


# --- FASTAPI INIT and CORS ---

app = FastAPI(
    title="DoodleFinder Backend API",
    description="Backend logic for the Animal Sketch Arena game. Integrates with Firebase Auth, Firestore, and Storage. Facilitates all game state, drawing, guessing, and leaderboard APIs.",
    version="1.0.0",
    openapi_tags=[
        {"name": "auth", "description": "User authentication and session APIs."},
        {"name": "drawing", "description": "Drawing management and upload APIs."},
        {"name": "guess", "description": "Guess submission and retrieval APIs."},
        {"name": "leaderboard", "description": "Leaderboard and stats APIs."}
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ROUTES ---


@app.get("/", tags=["root"])
def health_check():
    """Basic health check endpoint."""
    return {"message": "Healthy"}


# -------------------------- AUTH --------------------------


@app.post('/login', response_model=LoginResponse, tags=["auth"], summary="Anonymous Login with Username", description="Logs in a user anonymously and registers a unique username (must be unused). Returns Firebase UID and token.")
def login(data: LoginRequest):
    # Check if username already exists in Firestore
    users_ref = db.collection("users")
    if users_ref.where("username", "==", data.username).get():
        raise HTTPException(status_code=409, detail="Username already exists")
    # Create Firebase anonymous account
    user = auth.create_user(display_name=data.username)
    # Register mapping in Firestore
    users_ref.document(user.uid).set({
        "username": data.username,
        "created_at": get_timestamp(),
    })
    # Custom token (for client exchange for actual ID token)
    token = auth.create_custom_token(user.uid).decode("utf-8")
    return LoginResponse(uid=user.uid, username=data.username, token=token)



# -------------------------- DASHBOARD / DRAWINGS --------------------------


@app.get('/drawings', response_model=List[DrawingMetadata], tags=["drawing"], summary="List all drawings (dashboard)", description="Fetch all drawing metadata for the dashboard. The leading one is marked with highlighted=True.")
def get_drawings():
    draws = db.collection("drawings").order_by("created_at", direction=firestore.Query.DESCENDING).limit(100).get()
    drawings = [drawing_doc_to_metadata(doc) for doc in draws]
    # highlight leading drawing at top: max correct_guess_count
    if drawings:
        max_count = max(d.correct_guess_count for d in drawings)
        for d in drawings:
            d.highlighted = d.correct_guess_count == max_count and max_count > 0
    return drawings


@app.get('/drawings/{drawing_id}', response_model=DrawingMetadata, tags=["drawing"], summary="Fetch drawing by ID")
def get_drawing_by_id(drawing_id: str):
    doc = db.collection("drawings").document(drawing_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return drawing_doc_to_metadata(doc)


# Add drawing: provide prompt (spin wheel)
@app.post('/prompt', tags=["drawing"], response_model=Dict[str, str], summary="Get random animal prompt")
def get_prompt():
    """Returns a random animal prompt for drawing."""
    return {"prompt": get_random_prompt()}


# Add drawing: upload drawing
@app.post('/drawings', tags=["drawing"], summary="Submit new drawing", description="Uploads a drawing and its metadata. Requires: prompt, image (multipart), and user token. Returns drawing metadata.")
async def submit_drawing(
    background_tasks: BackgroundTasks,
    prompt: str = Form(..., description="Prompt used (animal)"),
    token: str = Form(..., description="Firebase user token"),
    file: UploadFile = File(...)):
    """Accepts a drawing image, stores in Firebase Storage, creates metadata in Firestore."""
    uid = get_uid_from_token(token)
    # Save to storage with unique filename
    drawing_id = uuid.uuid4().hex
    ext = os.path.splitext(file.filename or "")[-1] or ".png"
    blob_name = f"drawings/{drawing_id}{ext}"
    blob = bucket.blob(blob_name)
    contents = await file.read()
    blob.upload_from_string(contents, content_type=file.content_type)
    blob.make_public()
    image_url = blob.public_url

    # Register in Firestore
    doc_ref = db.collection("drawings").document(drawing_id)
    doc_ref.set({
        "prompt": prompt,
        "creator_uid": uid,
        "created_at": get_timestamp(),
        "image_url": image_url,
        "correct_guessers": [],
        "guesses": [],
        "wrong_guesses": [],
        "highlighted": False,
    })
    # increment user's created count
    user_ref = db.collection("users").document(uid)
    user_ref.set({"drawings_created": firestore.Increment(1)}, merge=True)
    # Return created drawing metadata
    doc = doc_ref.get()
    return drawing_doc_to_metadata(doc)


# -------------------------- GUESSING --------------------------


@app.post("/guess", response_model=GuessResponse, tags=["guess"], summary="Submit a guess for a drawing")
def submit_guess(data: GuessRequest, token: str = Form(...)):
    """Accepts a guess for a drawing. Validates, updates Firestore fields, enforces single guess per drawing/user."""
    uid = get_uid_from_token(token)
    drawing_id = data.drawing_id.strip()
    guess = data.guess.strip().lower()
    drawing_ref = db.collection("drawings").document(drawing_id)

    doc = drawing_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Drawing not found")
    d = doc.to_dict()

    if uid == d["creator_uid"]:
        return GuessResponse(status="fail", correct=False, message="Can't guess your own drawing.", correct_guess_count=len(set(d.get("correct_guessers", []))), wrong_guesses=d.get("wrong_guesses", []))

    # Only one guess per user per drawing
    if uid in d.get("correct_guessers", []):
        return GuessResponse(status="fail", correct=True, message="Already guessed this drawing correctly.", correct_guess_count=len(set(d.get("correct_guessers", []))), wrong_guesses=d.get("wrong_guesses", []))
    if uid in d.get("guesses", []):
        return GuessResponse(status="fail", correct=False, message="Already made a guess for this drawing.", correct_guess_count=len(set(d.get("correct_guessers", []))), wrong_guesses=d.get("wrong_guesses", []))

    # Is guess correct?
    correct = guess == d["prompt"].lower()
    update_data = {}

    if correct:
        # Add to correct_guessers and guesses
        update_data["correct_guessers"] = firestore.ArrayUnion([uid])
        update_data["guesses"] = firestore.ArrayUnion([uid])
        # Increment user's correct_guess count
        user_ref = db.collection("users").document(uid)
        user_ref.set({"correct_guesses": firestore.Increment(1)}, merge=True)
        msg = "Correct!"
    else:
        # Add uid to guesses and wrong_guesses
        update_data["guesses"] = firestore.ArrayUnion([uid])
        update_data["wrong_guesses"] = firestore.ArrayUnion([guess])
        msg = "Wrong guess."

    drawing_ref.update(update_data)
    # Return response with fresh counts
    doc = drawing_ref.get()
    d = doc.to_dict()
    return GuessResponse(
        status="ok",
        correct=correct,
        message=msg,
        correct_guess_count=len(set(d.get("correct_guessers", []))),
        wrong_guesses=list(set(d.get("wrong_guesses", [])))
    )


@app.get("/guesses/{drawing_id}", tags=["guess"], response_model=Dict[str, Any], summary="Get guesses for drawing (per user)")
def get_guesses(drawing_id: str, token: Optional[str] = None):
    """Fetches list of user guesses and wrong guesses for a drawing."""
    doc = db.collection("drawings").document(drawing_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Drawing not found")
    d = doc.to_dict()
    response = {
        "guesses": list(set(d.get("guesses", []))),
        "wrong_guesses": list(set(d.get("wrong_guesses", []))),
        "correct_guess_count": len(set(d.get("correct_guessers", []))),
    }
    # Optionally: is this user in guesses, marked
    if token:
        try:
            uid = get_uid_from_token(token)
            response["has_guessed"] = uid in d.get("guesses", [])
            response["guessed_correctly"] = uid in d.get("correct_guessers", [])
        except:
            response["has_guessed"] = False
            response["guessed_correctly"] = False
    return response

# -------------------------- LEADERBOARD --------------------------

@app.get("/leaderboard", tags=["leaderboard"], response_model=LeaderboardResponse, summary="Get leaderboard")
def get_leaderboard():
    """Get a sorted leaderboard (top 10) by number of correct guesses, then drawings created."""
    users = db.collection("users").get()
    leaderboard = []
    for u in users:
        d = u.to_dict()
        leaderboard.append({
            "username": d.get("username", "anon"),
            "correct_guesses": d.get("correct_guesses", 0),
            "drawings_created": d.get("drawings_created", 0),
        })
    leaderboard.sort(key=leaderboard_sort)
    entries = [LeaderboardEntry(**e) for e in leaderboard[:10]]
    return LeaderboardResponse(leaderboard=entries)

# -------------------------- REAL-TIME SUPPORT NOTE --------------------------

@app.get("/docs/websockets", tags=["root"], summary="Real-time/WebSocket Info", description="Firebase real-time updates are pushed via Firestore listeners on the frontend. Backend exposes REST only.")
def websocket_info():
    return {
        "note": "For real-time updates, use Firestore listeners on 'drawings' and 'leaderboard' collections with snapshot handlers from the frontend. This FastAPI backend offers REST endpoints only."
    }
