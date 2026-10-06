# Trader samples shipped in the image

Public Hyperliquid wallet fills (on-chain, public), hand-picked as illustrative examples. Not Bitget users and not the owner's account. Provenance label in the app: REAL_PLATFORM_PUBLIC.

Anonymised by scripts/prepare_samples.py: only the wallets the app uses are copied; order ids are replaced by order-preserving rank numbers; the full addresses (in the source summary.json) are not shipped. The app shows aliases only. The ledger was re-run on each copy and matched the original exactly.

| Alias | Role | Fills | Round trips |
|---|---|---|---|
| Wallet A | control | 3153 | 83 |
| Wallet B | candidate | 10000 | 112 |
| Wallet C | candidate | 10000 | 275 |
| Wallet D | disciplined | 4795 | 319 |
| Wallet E | candidate | 10000 | 224 |

Wallet F in the app is simulated (SIM_PLANTED) and needs no file.
