import os
import cv2
import numpy as np
from pyzbar.pyzbar import decode
from openpyxl import load_workbook
from pillow_heif import register_heif_opener
from PIL import Image

# === CONFIGURATION ===
input_folder = r"C:\Users\javic\Pictures\plates"
lamp_template = r"C:\Users\javic\Pictures\qr_reader\LAMP-X.xlsx"
qpcr_template = r"C:\Users\javic\Pictures\\qr_reader\QPCR-X.xlsx"

# Output folders
base_output = os.path.join(input_folder, "plate_output")
annotated_dir = os.path.join(base_output, "annotated_images")
filled_dir = os.path.join(base_output, "filled_excels")
os.makedirs(annotated_dir, exist_ok=True)
os.makedirs(filled_dir, exist_ok=True)

COLS = 8
ROWS = 12
MARGIN = 12
CROP_WIDTH = 2180
CROP_HEIGHT = 3940

register_heif_opener()

# Ask user which template to use (only once per batch)
while True:
    template_choice = input("Enter template to use (LAMP or QPCR): ").strip().upper()
    if template_choice in ["LAMP", "QPCR"]:
        break
    print("Invalid input. Please type 'LAMP' or 'QPCR'.")

template_path = lamp_template if template_choice == "LAMP" else qpcr_template

# === UTILITIES ===
def add_white_border(img, pixels=40):
    return cv2.copyMakeBorder(
        img, pixels, pixels, pixels, pixels,
        cv2.BORDER_CONSTANT, value=[255, 255, 255]
    )

def try_rotations(img, angles=(15, -15, 30, -30)):
    for angle in angles:
        M = cv2.getRotationMatrix2D((img.shape[1] // 2, img.shape[0] // 2), angle, 1.0)
        rotated = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), borderValue=(255, 255, 255))
        result = decode(rotated)
        if result:
            return result
    return None

# === PROCESS EACH .HEIC IMAGE ===
for filename in os.listdir(input_folder):
    if not filename.lower().endswith(".heic"):
        continue

    basename = os.path.splitext(filename)[0]
    heic_path = os.path.join(input_folder, filename)
    print(f"🔍 Processing: {filename}")

    try:
        pil_img = Image.open(heic_path).convert("RGB")
    except Exception as e:
        print(f"❌ Failed to read image {filename}: {e}")
        continue

    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    img_h, img_w = img.shape[:2]
    x = (img_w - CROP_WIDTH) // 2
    y = (img_h - CROP_HEIGHT) // 2
    cropped_img = img[y:y+CROP_HEIGHT, x:x+CROP_WIDTH]

    cell_w = CROP_WIDTH // COLS
    cell_h = CROP_HEIGHT // ROWS

    wb = load_workbook(template_path)
    ws = wb["samples"]

    col_labels = list("ABCDEFGH")
    positions = [f"{col}{row+1}" for row in range(ROWS) for col in col_labels]

    debug_img = cropped_img.copy()
    results = []

    for pos in positions:
        row = int(pos[1:]) - 1
        col = 7 - col_labels.index(pos[0])  # A1 top-right

        x0 = col * cell_w
        y0 = row * cell_h
        x1 = max(x0 - MARGIN, 0)
        y1 = max(y0 - MARGIN, 0)
        x2 = min(x0 + cell_w + MARGIN, cropped_img.shape[1])
        y2 = min(y0 + cell_h + MARGIN, cropped_img.shape[0])

        crop = cropped_img[y1:y2, x1:x2]
        crop = add_white_border(crop)

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        sharp = cv2.addWeighted(gray, 2.0, blur, -1.0, 0)
        _, thresh = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        qrs = decode(crop) or decode(gray) or decode(thresh)
        if not qrs:
            qrs = try_rotations(crop) or try_rotations(gray) or try_rotations(thresh)

        if qrs:
            qr_data = qrs[0].data.decode("utf-8").strip()
            results.append((pos, qr_data))
            cv2.putText(debug_img, f"{pos}: {qr_data}", (x1 + 3, y1 + 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 255, 0), 1)
        else:
            results.append((pos, ""))
            cv2.putText(debug_img, f"{pos}: ---", (x1 + 3, y1 + 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)

        cv2.rectangle(debug_img, (x1, y1), (x2, y2), (255, 0, 0), 1)
        cv2.putText(debug_img, pos, (x1 + 5, y1 + 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

    # === Sort and populate into Excel
    def well_sort_key(entry):
        col = ord(entry[0][0]) - ord('A')
        row = int(entry[0][1:])
        return (row, col)

    results_sorted = sorted(results, key=well_sort_key)
    for idx, (pos, code) in enumerate(results_sorted):
        ws[f"B{idx + 2}"] = pos
        ws[f"C{idx + 2}"] = code

    # === Save output
    annotated_path = os.path.join(annotated_dir, f"{basename}_annotated.jpg")
    filled_path = os.path.join(filled_dir, f"{basename}_filled.xlsx")

    wb.save(filled_path)
    cv2.imwrite(annotated_path, debug_img)

    total = len(results_sorted)
    success = sum(1 for _, val in results_sorted if val.strip())
    failed = total - success
    failed_pos = [p for p, v in results_sorted if not v.strip()]

    print(f"✅ Done with {filename}")
    print(f"✔️ {success}/{total} scanned")
    if failed:
        print(f"❌ {failed} failed at: {', '.join(failed_pos)}")
    print("------")
