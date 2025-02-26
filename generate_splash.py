from PIL import Image, ImageDraw, ImageFont
import os

# Create static/icons directory if it doesn't exist
os.makedirs('static/icons', exist_ok=True)

# Splash screen sizes for different iOS devices
splash_sizes = [
    (640, 1136),  # iPhone 5
    (750, 1334),  # iPhone 6/7/8
    (828, 1792),  # iPhone XR
    (1125, 2436), # iPhone X/XS
    (1170, 2532), # iPhone 12/13
    (1179, 2556), # iPhone 14 Pro
    (1284, 2778), # iPhone 12 Pro Max
    (1290, 2796), # iPhone 14 Pro Max
]

# Background color from manifest
bg_color = "#2c3e50"

# Create splash screens
for width, height in splash_sizes:
    # Create new image with background color
    image = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(image)
    
    # Load the icon
    icon = Image.open('static/icons/icon-512x512.png')
    
    # Calculate icon size (30% of the smaller dimension)
    icon_size = int(min(width, height) * 0.3)
    icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
    
    # Calculate position to center the icon
    icon_x = (width - icon_size) // 2
    icon_y = (height - icon_size) // 2
    
    # Paste the icon
    image.paste(icon, (icon_x, icon_y), icon if icon.mode == 'RGBA' else None)
    
    # Save the splash screen
    image.save(f'static/icons/splash-{width}x{height}.png', 'PNG')

print("Splash screens generated successfully!") 