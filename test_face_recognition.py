import os
import face_recognition
import cv2

KNOWN_FACES_DIR = "known_faces"
TEST_IMAGE_PATH = "test.jpg"  # Replace with your own test image

def load_known_faces():
    encodings = []
    names = []

    for filename in os.listdir(KNOWN_FACES_DIR):
        path = os.path.join(KNOWN_FACES_DIR, filename)
        image = face_recognition.load_image_file(path)
        try:
            encoding = face_recognition.face_encodings(image)[0]
            encodings.append(encoding)
            names.append(os.path.splitext(filename)[0])
        except IndexError:
            print(f"❌ No face found in {filename}. Skipping.")

    return encodings, names

def recognize_faces(test_image_path):
    print(f"🔍 Loading test image: {test_image_path}")
    image = face_recognition.load_image_file(test_image_path)
    face_locations = face_recognition.face_locations(image)
    face_encodings = face_recognition.face_encodings(image, face_locations)

    known_encodings, known_names = load_known_faces()

    image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    for (top, right, bottom, left), encoding in zip(face_locations, face_encodings):
        matches = face_recognition.compare_faces(known_encodings, encoding)
        name = "Unknown"

        if True in matches:
            match_index = matches.index(True)
            name = known_names[match_index]

        cv2.rectangle(image_bgr, (left, top), (right, bottom), (0, 255, 0), 2)
        cv2.putText(image_bgr, name, (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)

        print(f"✅ Face recognized: {name}")

    cv2.imshow("Result", image_bgr)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    if os.path.exists(TEST_IMAGE_PATH):
        recognize_faces(TEST_IMAGE_PATH)
    else:
        print(f"❗ Please provide a test image named '{TEST_IMAGE_PATH}' in this directory.")
