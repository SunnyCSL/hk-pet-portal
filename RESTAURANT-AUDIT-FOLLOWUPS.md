# 餐廳名單審計 — 跟進紀錄

## 2026-10-25 18:00 每週審計

審計結果：正常。DB↔FEHD 新除名 0、新獲准未入 DB 0、網站↔FEHD 失效 0 / 缺漏 0。
FEHD 名單更新 2026-10-23，999 個牌照；DB active 1035 行／999 個唯一牌照（全中）。

### 待跟進（非阻斷，屬資料衛生）
- DB 有 4 行 `status=active` 但 `license_no` 為空（id 834–837：HYGGE 油尖區、喜點 深水埗區、
  OMG緊張咖哩麵 深水埗區、Sparkling House Seafood & Oyster Bar 觀塘區），地址亦只有區名。
  同名有牌照版本已存在 → 疑似重複行；因 `lic()` 為空會被 diff 略過（比較器盲點）。
- 網站 `restaurants.json` 共 1000 行：999 行有牌照且全對 FEHD，另 1 行 HYGGE（油尖區、無牌照號）
  為無牌複製品；`site_licenses()` 過濾空牌照所以顯示 999。
- 建議下次同步時：為 4 行補牌照或標 `flagged`；移除網站無牌照重複行。
