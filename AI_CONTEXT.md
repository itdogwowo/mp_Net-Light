```markdown
# AI_CONTEXT.md — mp_Net-Light（協議/現況/擴展基礎說明）

> 用途：下次找 AI/工程師擴展功能時，直接貼這份文件即可快速對齊背景與約束，避免重複說明。

---

## 0) 專案簡述
mp_Net-Light 是一個 Server ⇄ MicroPython Client（ESP 系列 MCU）之間的控制與資料傳輸系統，主目標是：
- 控制/監察 MCU（狀態、配置、檔案傳輸等）
- 支援燈效資料（raw bytes）串流播放（之後要做 UDP streaming）

Client 是 **單核心**，對延遲、記憶體、GC 抖動敏感，因此協議設計追求：
- **二進位、極簡、可擴展**
- 同一套 encoder/decoder 可跨通道（TCP/UDP/串口/檔案）
- 可離線測試（不依賴網路）

---

## 1) 通道設計（現階段）
現階段只保留兩個 port（或可抽象為兩條通道）：

1) **TCP 通道**：控制/狀態/檔案傳輸（可靠、會黏包/拆包，所以需 stream parser）
2) **UDP 通道**：燈效 streaming（低延遲、可丟包；尚未完成 streaming 協議與實作）

> 協議層不綁定 LED 型號或 LED 數量上限；上限由應用層配置/協商決定。

---

## 2) 二進位封包協議（已定稿）
### 2.1 封包格式（VER=3）
```
SOF(2)  VER(1)  ADDR(2)  CMD(2)  LEN(2)  DATA(LEN)  CRC16(2)
```

- SOF：固定 `b"NL"`（2 bytes）
- VER：固定 `3`（1 byte）
- ADDR：uint16 little-endian（外層目的地址）
  - `0xFFFF` 表示 broadcast
- CMD：uint16 little-endian
- LEN：uint16 little-endian（此封包 DATA 長度）
- DATA：payload bytes
- CRC16：CRC16-CCITT-FALSE（poly=0x1021, init=0xFFFF）
  - CRC 覆蓋範圍：`VER..LEN + DATA`（不包含 SOF）

### 2.2 解析策略（固定）
**策略一（安全、簡化）**：
- 必須完整收齊一幀（HDR+DATA+CRC）
- 驗證 CRC16
- 再做 addr/cmd/data 的進一步處理

### 2.3 `max_len` 的意義
- `LEN(2)` 是對端宣告的單包 payload 長度
- `max_len` 是接收端本地的「單包可接受上限」，用來防止誤同步讀到超大 LEN 導致等待巨包/爆 RAM

---

## 3) 應用層規則（非常重要：已定稿）
### 3.1 所有 CMD 的 DATA 都必定以 `dst_addr(u16)` 開頭
即：
```
DATA = dst_addr(u16 LE) + body(...)
```

原因：
- 為未來可能的 feature（如轉寄/中繼）預留空間
- 即使 header.addr 是外層目的地，data.dst_addr 可作為內層目的地（目前僅保留欄位，不做完整路由功能）

> 注意：目前系統尚未實作真正 routing/relay（例如 TTL、msg_id 等），只是保留 data.dst_addr 欄位與統一格式。

---

## 4) 已完成模組/檔案
### 4.1 `proto.py`
提供：
- `pack_packet(cmd, payload, addr=..., ver=3) -> bytes`
- `parse_one(packet_bytes) -> (ver, addr, cmd, payload) or None`
- `StreamParser(max_len, accept_addr)`：TCP/串口流式解析器
  - 支援黏包/拆包
  - SOF resync（丟 1 byte 重新同步）
  - MicroPython 相容：避免 `del bytearray[:n]`，用 `self.buf = self.buf[n:]`
- CRC16 已改為 **256-entry lookup table 加速版**（與 bitwise 結果一致）

### 4.2 `file_transfer.py`（檔案接收狀態機）
- 已完成「檔案傳輸三件套」的接收端狀態機：
  - `CMD_FILE_BEGIN = 0x2001`
  - `CMD_FILE_CHUNK = 0x2002`
  - `CMD_FILE_END   = 0x2003`
- 所有 payload 均以 `dst_addr(u16)` 開頭（符合應用層規則）
- 支援：
  - chunk 以 `offset(u32)` 隨機寫入（seek + write）
  - 重組到 Flash 檔案
  - 傳輸結束後以 SHA256（hashlib）串流方式驗證（digest 32 bytes）
- 不回 ACK/ERR：由上層最後統一查詢狀態或依 END 結果決定

### 4.3 離線測試工具
- `offline_selftest.py`
  - 測 StreamParser 在雜訊/壞 CRC/非目標 addr/拆包黏包下能正常 resync 並解析
- `offline_manual_tester_cn.py`
  - 中文輸出
  - 支援：
    - 手動輸入 data -> pack -> 模擬 TCP 拆包 -> parse -> compare
    - 使用 FILE_BEGIN/CHUNK/END 完整離線跑一次檔案傳輸並做 SHA256 驗證
  - 計時輸出：封包化/解析接收/sha 驗證耗時

---

## 5) 未完成/待擴展方向（AI/工程師下一步可做）
### 5.1 UDP streaming（重點待做）
需要設計並實作：
- `CMD_STREAM_FRAME`（建議 cmd 範圍 0x3000+）
- payload 格式要符合「data 前 2 bytes 為 dst_addr」規則，例如：
  - `dst_addr(u16) + frame_id(u32) + raw_bytes(...)`
  - 若需分片：加 `frag_i(u16) frag_n(u16)` 或 `offset(u16)` 等
- 丟幀策略：低延遲為主（可丟包不重送）
- LED driver 抽象（neopixel/spi/pwm 等）

### 5.2 查詢狀態（你偏好的模式）
可新增：
- `CMD_STATUS_GET / CMD_STATUS_RSP`
- 或統一 `CMD_QUERY` 類型
狀態包含：
- file_rx active / last_error / last_result（sha mismatch 等）
- streaming 狀態（fps/drop/free_mem）

### 5.3 未來（可能）routing/relay
目前僅保留 data.dst_addr，尚不具備完整路由能力。
若要正式做 relay，需要至少新增：
- TTL / hops
- message id（去重）
- 轉寄策略（header.addr 是 next-hop 還是 final-dst）
這部分應做為新版本或新增擴展欄位，不建議硬塞在現有最小規格中。

---

## 6) 擴展時必須遵守的約束
1) 不修改既定 packet header（除非升版本）
2) 所有 CMD 的 DATA 一律以 `dst_addr(u16)` 開頭（已定稿）
3) Client 單核心、資源有限：避免大量配置、避免阻塞
4) streaming（UDP）以低延遲為優先：允許丟包；可靠傳輸走 TCP + chunk 模式
5) 保持格式少、可重複使用：擴展主要靠 CMD + DATA 定義

---

## 7) 下次詢問 AI 的模板（直接複製貼上）
> 我在做 mp_Net-Light。協議固定為二進位：
> SOF(2)=b'NL', VER(1)=3, ADDR(2), CMD(2), LEN(2), DATA, CRC16(2)。
> CRC16-CCITT-FALSE 覆蓋 VER..DATA（不含 SOF），CRC16 table 加速版已完成。
> StreamParser 支援 TCP 黏包/拆包與 resync。
> 應用層規則：所有 CMD 的 DATA 必定以 dst_addr(u16 LE) 開頭。
> 現已完成 FILE_BEGIN/CHUNK/END 檔案接收（seek 寫入 + SHA256 驗證）。
> 我現在要新增功能：{描述功能，例如 UDP streaming CMD_STREAM_FRAME、狀態查詢、或 LED driver 抽象}。
> 請遵守既定協議與 DATA 前綴規則，提供 MicroPython 端可直接使用的程式骨架與必要註釋。

---
```