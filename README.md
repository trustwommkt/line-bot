# LINE Bot - 訊息摘要助理

## 功能
- 加入客戶群組後，自動記錄所有對話
- 每天 17:00 自動整理重點並發送到內部群組
- 隨時輸入「整理」或「摘要」立即產生摘要

## 環境變數設定
| 變數名稱 | 說明 |
|---------|------|
| LINE_CHANNEL_ACCESS_TOKEN | LINE Bot Channel Access Token |
| LINE_CHANNEL_SECRET | LINE Bot Channel Secret |
| GEMINI_API_KEY | Google Gemini API Key（免費） |
| INTERNAL_GROUP_ID | 內部群組的 Group ID |

## 如何取得 INTERNAL_GROUP_ID
1. 將 Bot 加入你的內部群組
2. 在群組輸入任意訊息
3. 到 Render 的 Log 中找到 group_id

## 部署到 Render
1. 把這個 repo 連結到 Render
2. 填入所有環境變數
3. 部署後把 Webhook URL 填入 LINE Developers

## 觸發指令
- 輸入「整理」、「摘要」、「重點」或「/summary」即可立即摘要
