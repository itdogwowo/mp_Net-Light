# AI_CONTEXT.md — mp_Net-Light 協議/接收器現況與擴展需求基礎

## 0. 專案簡述
mp_Net-Light 是一個 Server ⇄ MicroPython Client 的控制與燈效播放系統。  
Client（ESP 系列 + MicroPython）為單核心，需要低延遲、低負擔的通訊與解析。

目前採用 **自定義二進位協議**，不依賴特定網路協定，可在 TCP/UDP/串口/檔案中重複使用同一套解包器。

---

## 1. 系統通道設計（現階段）
因單核心 + 已具體協議，現階段只保留兩個 port：

- **TCP port**：控制/狀態/檔案傳輸（可靠、流式、可能黏包/拆包）
- **UDP port**：燈效 streaming（低延遲，允許丟包）

> 協議層不限制硬體（ESP 全家桶、單色或 RGB/RGBW 皆可），上限由應用層/配置決定。

---

## 2. 二進位封包格式（已定稿：VER=2）
封包格式：

```
SOF(2)  VER(1)  SRC(2)  DST(2)  CMD(2)  LEN(2)  DATA(LEN)  CRC16(2)
```

- `SOF`：固定 `b"NL"` (2 bytes)
- `VER`：目前固定 `2`
- `SRC`：來源 address，uint16 little-endian
- `DST`：目的 address，uint16 little-endian
- `CMD`：操作碼，uint16 little-endian
- `LEN`：DATA 長度，uint16 little-endian
- `DATA`：payload bytes
- `CRC16`：CRC16-CCITT-FALSE（poly=0x1021, init=0xFFFF）
  - CRC 計算範圍：`VER..LEN + DATA`（不包含 SOF）

### Address 約定
- `DST = 0xFFFF`：broadcast
- 其他：設備地址（uint16）
- Client 會配置 `MY_ADDR`

---

## 3. Parser / 解包器（已完成）
### 3.1 協議層檔案：`proto.py`
已實作：
- `pack_packet(cmd, payload, src, dst, ver=2) -> bytes`
- `parse_one(packet_bytes) -> (ver, src, dst, cmd, payload) or None`（單包解析，適合 UDP/檔案）
- `StreamParser(max_len=..., accept_dst=MY_ADDR)`（流式解析，適合 TCP/串口）

### 3.2 StreamParser 特性
- 解決 TCP 黏包/拆包：`feed()` + `pop()` 解析出 0..N 個封包
- SOF 同步：在 buffer 中搜尋 `b"NL"`
- CRC16 驗證：CRC 不對會丟 1 byte 重新同步（resync）
- `max_len`：**單包 DATA 長度安全上限**（防止誤同步讀到超大 LEN 造成卡死/爆 RAM）
- `accept_dst`：只 yield `DST==MY_ADDR` 或 `DST==broadcast` 的封包（但仍會 consume 非目標封包，避免 stream 卡住）
- MicroPython 相容性：避免 `del bytearray[:n]` 切片刪除，改用 `self.buf = self.buf[n:]`

### 3.3 已驗證
- 有離線 selftest：能處理雜訊、壞 CRC、非目標 DST、拆包黏包
- 在 MicroPython 上跑通並 PASS

---

## 4. 重要約束（擴展功能時必須遵守）
1) **盡量少格式**：封包 header 固定，不新增文字協議；擴展放在 CMD 與 DATA 中
2) **單核心 MCU**：接收/解析不可長時間阻塞；控制與 streaming 的 CPU/記憶體負擔要可控
3) **UDP streaming 低延遲**：允許丟包，通常不做重送；如需可靠傳輸，應走 TCP/檔案 chunk 模式
4) **協議層不綁 LED 類型**：像素格式、LED 數量、frame_bytes 等在上層協商
5) **每個封包都必須 CRC16 正確**；CRC 覆蓋範圍固定（不含 SOF）

---

## 5. 待擴展項目（AI/工程師可基於此直接做）
以下擴展都應該「只新增 CMD 定義與 DATA 格式」，不要改 header：

### 5.1 CMD 規劃建議（示例，未完全定稿）
- 控制類（TCP）：
  - `CMD_HELLO`：設備能力/版本回報
  - `CMD_SET_ADDR`：server 指派地址（可選）
  - `CMD_GET_STATUS` / `CMD_STATUS`：查詢/回報狀態
  - `CMD_STREAM_OPEN` / `CMD_STREAM_CLOSE`：建立 streaming 參數（mtu、pixfmt、frame_bytes、fps）
- 檔案類（TCP）：
  - `CMD_FILE_BEGIN` / `CMD_FILE_CHUNK` / `CMD_FILE_END`
  - chunk payload 建議包含：`file_id(u32) + offset(u32) + data...` 或更簡化只 offset
  - 完成後做 SHA256 驗證
- 串流類（UDP）：
  - `CMD_STREAM_FRAME`：payload 建議包含 `frame_id(u32)` + raw bytes
  - 若需分片：加入 `frag_i(u16) frag_n(u16)` + chunk bytes

### 5.2 檔案驗證
- 建議用 SHA256：
  - sender 發 `FILE_END` 帶 sha256
  - receiver 完成後計算 sha256 比對並回覆結果

### 5.3 性能優化方向（可後續）
- StreamParser 若需更高吞吐，可改 ring buffer / memoryview 降低拷貝
- UDP streaming 接收端需避免大量 Python loop，盡量用 memoryview/預分配 buffer

---

## 6. 離線測試工具（已存在/可繼續擴展）
- `offline_selftest.py`：自動測試拆包/黏包/雜訊/壞 CRC/非目標 DST
- `offline_manual_tester_cn.py`（規劃中或已有）：手動輸入 data -> pack -> parse -> compare；檔案分包重組並比對 + sha256 + 計時

離線測試的目標：
- 不依賴網路、自己對自己測
- 可用於回歸測試 parser 正確性與分包策略

---

## 7. 你在擴展時應該問 AI 的問題模板（直接複製貼上）
以下文字你下次問 AI 時可以直接貼，省時間：

**模板：**

> 我在做 mp_Net-Light。協議固定為二進位：
> SOF(2)=b'NL', VER(1)=2, SRC(2), DST(2), CMD(2), LEN(2), DATA, CRC16(2)。
> CRC16-CCITT-FALSE 覆蓋 VER..DATA（不含 SOF）。  
> MicroPython 單核心，現有 `proto.py` 提供 `pack_packet/parse_one/StreamParser`，StreamParser 支援 TCP 黏包拆包、CRC resync、accept_dst 過濾。  
> 我現在要新增功能：{描述你要的功能，例如：UDP streaming 的 CMD_STREAM_FRAME payload 規格 + 重組策略 / TCP 檔案傳輸 begin-chunk-end + sha256 驗證 / 狀態查詢等}。  
> 請在不改 header 的前提下，只新增 CMD 與 DATA 格式，並提供 MicroPython 端處理骨架與必要注釋。

---

## 8. 目前最關鍵的未知/待定參數（擴展前需確認）
- UDP streaming 是否支援分片（frag）？常見 LED 數量導致一幀 bytes 是否能塞進 mtu？
- 檔案傳輸 chunk_size（建議 512/1024/2048）
- CMD 分配策略：是否用高位分類（例：0x1xxx 控制、0x2xxx 檔案、0x3xxx 串流）

---

## 9. 附：max_len 的設計意義（避免誤會）
- `LEN(2)` 是對端宣告的 payload 長度（單包）
- `max_len` 是本地安全上限（防止誤同步/惡意長度導致 parser 等待巨包或 OOM）
- 大資料（檔案/流）應採用分包策略，多個封包組成一個大消息，不要單包超大 LEN

---

如果你願意，我也可以再幫你補一份更「正式協議文件」`PROTOCOL_SPEC.md`（只寫規格、不寫背景），以及把 `CMD 編號範圍規劃表` 做成一張表，讓後續擴展更一致。