"""Quick check for 12.pdf."""
import fitz

file_path = r"d:\qp\Questgen\paper_generator\uploads\12.pdf"
doc = fitz.open(file_path)
page = doc[0]

words = page.get_text("words")
print(f"Total words: {len(words)}")

if words:
    print(f"\nFirst 30 words:")
    for i, w in enumerate(words[:30]):
        print(f"  {i+1}. '{w[4]}' at Y={w[1]:.0f}")
else:
    images = page.get_images(full=True)
    print(f"Images: {len(images)}")
    if images:
        print("This PDF is image-based")

doc.close()
