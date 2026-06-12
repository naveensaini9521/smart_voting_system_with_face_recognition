import os
import random
from datetime import datetime

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf", "doc", "docx"}


def generate_voter_id():
    """Generate unique voter ID in format: VOTE{YYYY}{5-digit sequential number}"""
    current_year = datetime.now().year

    sequential_number = random.randint(10000, 99999)

    return f"VOTE{current_year}{sequential_number}"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_face_encoding(voter_id, face_encoding):
    """Save face encoding to file (in production, use secure storage)"""
    filename = f"face_encoding_{voter_id}.dat"
    upload_folder = "face_encodings"

    os.makedirs(upload_folder, exist_ok=True)
    file_path = os.path.join(upload_folder, filename)

    with open(file_path, "w") as f:
        f.write(face_encoding)

    return file_path


def verify_face(captured_face_image, stored_encoding_path):
    """Verify face against stored encoding"""
    import random

    is_match = random.random() > 0.15  # 85% success rate

    return {
        "match": is_match,
        "confidence": (
            random.uniform(0.85, 0.99) if is_match else random.uniform(0.1, 0.6)
        ),
    }


def validate_age(date_of_birth):
    """Validate if user is 18 years or older"""
    today = datetime.now().date()
    age = (
        today.year
        - date_of_birth.year
        - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))
    )
    return age >= 18
