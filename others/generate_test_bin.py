"""
生成測試用 .bin 文件
═══════════════════════════════════════════════════════
功能:
1. 小文件 (單次 PUSH)
2. 大文件 (多次 PUSH)
3. 各種動畫效果
"""
import struct
import os
import math

def generate_rainbow_block(num_leds, num_frames, output_path):
    """
    生成彩虹動畫
    
    參數:
        num_leds: LED 數量
        num_frames: 幀數
        output_path: 輸出路徑
    """
    print(f"🎨 Generating {output_path}...")
    
    with open(output_path, "wb") as f:
        for frame_idx in range(num_frames):
            for led_idx in range(num_leds):
                hue = (led_idx + frame_idx * 2) % 256
                
                # HSV to RGB
                if hue < 85:
                    r = 255 - hue * 3
                    g = hue * 3
                    b = 0
                elif hue < 170:
                    hue -= 85
                    r = 0
                    g = 255 - hue * 3
                    b = hue * 3
                else:
                    hue -= 170
                    r = hue * 3
                    g = 0
                    b = 255 - hue * 3
                
                brightness = 128
                r = (r * brightness) // 255
                g = (g * brightness) // 255
                b = (b * brightness) // 255
                
                f.write(struct.pack("BBBB", r, g, b, 0))
    
    size = os.path.getsize(output_path)
    print(f"✅ Generated: {output_path} ({size} bytes, {size // 1024} KB)")

def generate_solid_color_block(num_leds, num_frames, color, output_path):
    """
    生成純色 Block
    
    參數:
        color: (R, G, B) 元組
    """
    print(f"🎨 Generating {output_path}...")
    
    r, g, b = color
    
    with open(output_path, "wb") as f:
        for _ in range(num_frames):
            for _ in range(num_leds):
                f.write(struct.pack("BBBB", r, g, b, 0))
    
    size = os.path.getsize(output_path)
    print(f"✅ Generated: {output_path} ({size} bytes, {size // 1024} KB)")

def generate_breathing_block(num_leds, num_frames, color, output_path):
    """
    生成呼吸燈 Block
    """
    print(f"🎨 Generating {output_path}...")
    
    base_r, base_g, base_b = color
    
    with open(output_path, "wb") as f:
        for frame_idx in range(num_frames):
            brightness = int((math.sin(frame_idx * 2 * math.pi / num_frames) + 1) * 127.5)
            
            r = (base_r * brightness) // 255
            g = (base_g * brightness) // 255
            b = (base_b * brightness) // 255
            
            for _ in range(num_leds):
                f.write(struct.pack("BBBB", r, g, b, 0))
    
    size = os.path.getsize(output_path)
    print(f"✅ Generated: {output_path} ({size} bytes, {size // 1024} KB)")

def generate_wave_block(num_leds, num_frames, output_path):
    """
    生成波浪動畫
    """
    print(f"🎨 Generating {output_path}...")
    
    with open(output_path, "wb") as f:
        for frame_idx in range(num_frames):
            for led_idx in range(num_leds):
                # 波浪公式
                wave = math.sin((led_idx / num_leds * 2 * math.pi) + (frame_idx / num_frames * 2 * math.pi))
                brightness = int((wave + 1) * 127.5)
                
                # 藍色波浪
                r = 0
                g = brightness // 2
                b = brightness
                
                f.write(struct.pack("BBBB", r, g, b, 0))
    
    size = os.path.getsize(output_path)
    print(f"✅ Generated: {output_path} ({size} bytes, {size // 1024} KB)")

if __name__ == "__main__":
    print("🚀 mp_Net-Light Test Data Generator")
    print("=" * 60)
    
    # ══════════════════════════════════════════════════
    # 小文件 (測試單次 PUSH)
    # ══════════════════════════════════════════════════
    print("\n📦 Generating Small Files (Single PUSH)...")
    
    NUM_LEDS_SMALL = 100
    NUM_FRAMES_SMALL = 60
    
    generate_rainbow_block(NUM_LEDS_SMALL, NUM_FRAMES_SMALL, "test_small_rainbow.bin")
    generate_solid_color_block(NUM_LEDS_SMALL, NUM_FRAMES_SMALL, (255, 0, 0), "test_small_red.bin")
    generate_breathing_block(NUM_LEDS_SMALL, NUM_FRAMES_SMALL, (0, 0, 255), "test_small_blue.bin")
    
    # ══════════════════════════════════════════════════
    # 大文件 (測試多次 PUSH)
    # ══════════════════════════════════════════════════
    print("\n📦 Generating Large Files (Multiple PUSH)...")
    
    NUM_LEDS_LARGE = 2000
    NUM_FRAMES_LARGE = 500
    
    generate_rainbow_block(NUM_LEDS_LARGE, NUM_FRAMES_LARGE, "test_large_rainbow.bin")
    generate_wave_block(NUM_LEDS_LARGE, NUM_FRAMES_LARGE, "test_large_wave.bin")
    
    # ══════════════════════════════════════════════════
    # 統計
    # ══════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("📊 Generation Complete!")
    print("=" * 60)
    
    total_size = 0
    for f in os.listdir('.'):
        if f.startswith('test_') and f.endswith('.bin'):
            size = os.path.getsize(f)
            total_size += size
            print(f"  {f:<30} {size:>10} bytes ({size // 1024} KB)")
    
    print("=" * 60)
    print(f"Total Size: {total_size} bytes ({total_size // 1024} KB)")
    print("=" * 60)
    
    # ══════════════════════════════════════════════════
    # 使用說明
    # ══════════════════════════════════════════════════
    print("\n📝 Usage Guide:")
    print("─" * 60)
    print("【小文件測試 (Flash 模式)】")
    print("1. Run test_pc_tool.py")
    print("2. Upload test_small_rainbow.bin → /data/0.bin")
    print("3. Upload test_small_red.bin → /data/1.bin")
    print("4. Upload test_small_blue.bin → /data/2.bin")
    print("5. Config: num_leds=100, f_per_block=60, mode=0")
    print("6. State Set: block_id=0~2, source=1")
    print("7. Play")
    print()
    print("【大文件測試 (RAM 模式)】")
    print("1. Config: num_leds=2000, f_per_block=50, mode=1")
    print("2. State Set: block_id=0, source=2")
    print("3. Push: test_large_rainbow.bin (分 10 次)")
    print("4. Play")
    print("─" * 60)