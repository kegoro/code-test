from PIL import Image
import os

src = r"C:\Users\sfudally\.claude\uploads\d2e0a2af-0ff7-41a8-a340-0083ecb0b219\7a75650c-IMG_7050.png"
im = Image.open(src).convert("RGB")
W, H = im.size
out = r"C:\Users\sfudally\Desktop\code test\_crop"
os.makedirs(out, exist_ok=True)

# 被動元件 = column 2 of 4 (index 2). x ~0.50W..0.72W. Rows of passive components.
x0, x1 = int(W * 0.49), int(W * 0.74)
band = im.crop((x0, 1000, x1, 1500))
band = band.resize((band.width * 4, band.height * 4), Image.LANCZOS)
band.save(os.path.join(out, "passive.png"))
print("done", band.size)
