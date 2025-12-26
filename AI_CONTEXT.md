# AI_CONTEXT.md — mp_Net-Light 協議/接收器現況（VER=3, ADDR(2)）

## 0. 專案簡述
mp_Net-Light：Server ⇄ MicroPython Client（ESP 系列）控制與燈效串流。
Client 單核心，需要低負擔、可擴展、可離線測試的通訊與解析。

## 1. 通道設計（現階段）
- TCP：控制/狀態/檔案（可靠，會黏包/拆包）
- UDP：燈效串流（低延遲，可丟包）

協議層不依賴網路協定，可用於 TCP/UDP/串口/檔案。

## 2. 二進位封包格式（已定稿）
```
SOF(2)  VER(1)  ADDR(2)  CMD(2)  LEN(2)  DATA(LEN)  CRC16(2)
```

- SOF：b'NL'
- VER：3
- ADDR：目的地址（uint16），0xFFFF = broadcast
- CMD：uint16
- LEN：uint16
- CRC16：CRC16-CCITT-FALSE，覆蓋 VER..DATA（不含 SOF）

## 3. 解析策略（Strategy 1）
- 必須完整收齊一幀（HDR+DATA+CRC）
- 驗 CRC
- 再檢查 addr 是否屬於自己或 broadcast
- 再 dispatch

## 4. 已完成程式
`proto.py`
- pack_packet(cmd, payload, addr)
- parse_one(packet)
- StreamParser(max_len, accept_addr)

StreamParser：
- 支援 TCP 黏包/拆包
- SOF resync
- max_len 防呆
- MicroPython 相容（不用 del bytearray slicing）

## 5. 離線測試工具
- offline_selftest.py：自動測試（雜訊/壞CRC/非自己addr/拆包黏包）
- offline_manual_tester_cn.py：中文手動測試（任意data/檔案分包重組/sha256/計時）

## 6. 擴展要求
擴展功能應只新增 CMD 與 DATA 格式，不改 header，保持格式最少。
```

---

# 5) 你現在需要做的操作（覆蓋舊檔）
把舊的 VER=2（SRC/DST）檔案覆蓋為以上 4 個檔案即可。

建議你在板子上執行順序：
1) `offline_selftest.py`（快速驗證 parser 沒壞）
2) `offline_manual_tester_cn.py`（手動/檔案分包驗證）

---

如果你要我再補一個 `net_rx.py`（TCP+UDP socket 接收器）也同步改成 VER=3 + ADDR(2)，我可以下一則直接給你，並且把 UDP/TCP 的 max_len 分別設為你指定的值（例如 TCP 4096、UDP 1400）。