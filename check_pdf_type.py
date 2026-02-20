"""Check if 2nd.pdf is image-based."""
import fitz

file_path = r"d:\qp\Questgen\paper_generator\2nd.pdf"
doc = fitz.open(file_path)

for page_num, page in enumerate(doc):
    print(f"\n=== PAGE {page_num + 1} ===")
    
    # Check for images
    images = page.get_images(full=True)
    print(f"Images on page: {len(images)}")
    for img in images:
        print(f"  Image: xref={img[0]}, width={img[2]}, height={img[3]}")
    
    # Check for drawings/paths
    drawings = page.get_drawings()
    print(f"Drawings/paths: {len(drawings)}")
    
    # Get raw text
    text = page.get_text()
    print(f"Raw text length: {len(text)} chars")
    if text.strip():
        print(f"Text preview: {text[:200]}")
    else:
        print("No text found - likely image-based PDF")
    
    # Page dimensions
    rect = page.rect
    print(f"Page size: {rect.width:.0f} x {rect.height:.0f}")

doc.close()
print("\n" + "="*50)
print("CONCLUSION: If Images > 0 and Text = 0, this is a scanned/image PDF")
print("OCR would be required to extract text from such PDFs.")
