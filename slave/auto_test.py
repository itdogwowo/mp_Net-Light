"""
auto_test_simple.py - 簡化版測試
═══════════════════════════════════════════════════════
聚焦問題排查
"""
import os
import time
import socket
import threading
import hashlib
import zlib
from test_pc_tool import PCTestTool, Proto, SchemaCodec

def simple_test():
    """簡化測試: 只測試基本連接和配置"""
    print("🧪 Simple Test")
    
    tool = PCTestTool()
    threading.Thread(target=tool.start_ws_server, daemon=True).start()
    time.sleep(1)
    
    # 廣播
    print("\n📡 Broadcasting...")
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    
    disc_data = SchemaCodec.encode(tool.store.get(0x1001), {
        "server_ip": tool.local_ip,
        "ws_url": f"ws://{tool.local_ip}:8000/ws"
    })
    
    for _ in range(3):
        udp_sock.sendto(Proto.pack(0x1001, disc_data), ('255.255.255.255', 9000))
        time.sleep(0.5)
    udp_sock.close()
    
    # 等待
    print("\n⏳ Waiting 10s...")
    time.sleep(10)
    
    if not tool.slaves:
        print("❌ No devices")
        return
    
    targets = [sid for sid, info in tool.slaves.items() if info.get("is_identified")]
    print(f"✅ Found: {targets}")
    
    # 配置
    print("\n📝 Configuring...")
    tool.send_to_targets(targets, 0x3001, {
        "num_leds": 100,
        "f_per_block": 60,
        "total_blocks": 10,
        "fps": 40,
        "mode": 2,
        "data_path": "/data/",
        "num_buffers": 3,
        "report_interval": 5000
    })
    
    time.sleep(2)
    
    # 上傳小文件到 Flash
    print("\n📝 Uploading test.bin to /data/data.bin...")
    
    if not os.path.exists("test.bin"):
        print("❌ test.bin not found")
        return
    
    with open("test.bin", "rb") as f:
        data = f.read()
    
    # 調整大小
    expected_size = 100 * 60 * 4  # 24000 bytes
    if len(data) < expected_size:
        data = data + b'\x00' * (expected_size - len(data))
    elif len(data) > expected_size:
        data = data[:expected_size]
    
    sha = hashlib.sha256(data).digest()
    f_id = 100
    chunk_size = 1024
    
    # BEGIN
    tool.send_to_targets(targets, 0x2001, {
        "file_id": f_id,
        "total_size": len(data),
        "chunk_size": chunk_size,
        "sha256": sha,
        "path": "/data/data.bin"
    })
    
    time.sleep(0.5)
    
    # CHUNK
    for off in range(0, len(data), chunk_size):
        chunk = data[off : off + chunk_size]
        
        for tid in targets:
            if tid not in tool.slaves:
                continue
            
            tool.slaves[tid]["ack_event"].clear()
            
            tool.send_to_targets([tid], 0x2002, {
                "file_id": f_id,
                "offset": off,
                "data": chunk
            })
            
            tool.slaves[tid]["ack_event"].wait(timeout=1.0)
        
        print(f"  📤 {min(off+chunk_size, len(data))}/{len(data)} bytes", end='\r')
    
    print()
    
    # END
    tool.send_to_targets(targets, 0x2003, {"file_id": f_id})
    time.sleep(1)
    
    print("✅ File uploaded")
    
    # 設置 Block 0
    print("\n📝 Setting Block 0 (Flash)...")
    tool.send_to_targets(targets, 0x3009, {
        "block_id": 0,
        "frame_offset": 0,
        "priority": 0,
        "source": 1
    })
    
    time.sleep(2)
    
    # 播放
    print("\n📝 Playing...")
    tool.send_to_targets(targets, 0x300A, {})
    
    print("\n✅ Test running, monitoring for 30s...")
    time.sleep(30)
    
    # 停止
    tool.send_to_targets(targets, 0x3002, {})
    print("\n⏹️ Stopped")

if __name__ == "__main__":
    simple_test()