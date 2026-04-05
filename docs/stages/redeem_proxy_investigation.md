# Исследование R1: Тип прокси Polymarket для MetaMask и путь исполнения redeemPositions

**Дата:** 2026-04-05
**Статус:** Research complete → **рекомендован Путь A (pre-validated signature)**

---

## TL;DR

- `PM_FUNDER_ADDRESS` — это **стандартный Gnosis Safe v1.3.0**, развёрнутый через Polymarket Safe Proxy Factory по адресу `0xaacFeEa03eB1561C4e67d661e40682Bd20E3541b`.
- Это **1-of-1 multisig**, единственный owner — ваш MetaMask EOA.
- Редим нужно исполнять через **`execTransaction`** на Safe, передавая туда calldata для `redeemPositions` на CTF-контракте.
- **Подпись в транзакции реально генерировать НЕ нужно**: используется трюк **"pre-validated signature"** (type `01`), работающий когда отправитель транзакции сам является owner-ом. Это единственный способ, идеально подходящий для автоматизации.
- Для этого не требуется `safe-eth-py` (но его можно использовать). Достаточно `web3.py` и ~50 строк кода.

---

## 1. Архитектура Polymarket Safe

### 1.1 Ключевые адреса на Polygon

| Контракт | Адрес | Назначение |
|----------|-------|------------|
| Polymarket Safe Proxy Factory | `0xaacFeEa03eB1561C4e67d661e40682Bd20E3541b` | Фабрика, разворачивает Safe по CREATE2 детерминированно от EOA |
| GnosisSafe Singleton (masterCopy) | читается из фабрики | Imlementation контракт (стандартный Safe v1.3.0) |
| ConditionalTokens (CTF) | `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` | Держит ERC1155 outcome-токены, здесь живёт `redeemPositions` |
| CTF Exchange | `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` | Для обычных рынков |
| NegRiskAdapter | `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296` | Для neg-risk рынков (split/merge/redeem идут через него) |
| USDC.e (collateral) | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` | Базовый collateral-токен Polymarket |

### 1.2 Структура вашего Safe

```
Polymarket Safe (PM_FUNDER_ADDRESS)
├── VERSION = "1.3.0" (стандартный GnosisSafe)
├── getThreshold() = 1
├── getOwners() = [ваш MetaMask EOA]
├── nonce() = <инкрементный, уникальный>
└── хранит:
    ├── ERC1155 CTF tokens (YES/NO outcome tokens)
    └── ERC20 USDC (приходит после успешного redeemPositions)
```

Factory контракт на Polygonscan (`0xaacFeEa0...`) показывает имя `"Polymarket Contract Proxy Factory"` и использует стандартный `GnosisSafeProxy` + `GnosisSafe` v1.3.0. Фабрика лишь немного кастомизирована для EIP-712 signing при gasless-деплое, но сам развёрнутый Safe — **полностью стандартный**.

### 1.3 Подтверждения из официальных источников

- Polymarket docs: *"For MetaMask users on Polymarket, Gnosis safe factories are employed, resulting in proxy wallets"*
- Polymarket/examples GitHub: *"Polymarket Safes: This is a slightly modified Gnosis safe ... It is a multisig with only 1 signer, the wallet used to sign into the website"*
- Bullpen docs: *"The proxy wallet is a Gnosis Safe with a single signer (you)"*
- polymarket-wallet-recovery (public repo, Jan 2026): *"Browser wallets (MetaMask, Coinbase Wallet, Rainbow, etc.) use Safe Wallets"* — поддерживает `Safe: { redeem: true, withdraw: true }`

---

## 2. Почему прямой `redeemPositions` от MetaMask EOA не работает

`redeemPositions` в CTF-контракте сжигает ERC1155 токены с баланса `msg.sender`. Когда вы вызываете его напрямую от своего MetaMask EOA — `msg.sender` = ваш EOA, но токены хранятся на Safe → `_batchBurn` падает/транзакция проходит но сжигать нечего → USDC не приходит.

**Правильная цепочка вызовов:**

```
MetaMask EOA (вы)
    │ tx.origin = EOA, msg.sender = EOA
    ▼
Safe.execTransaction(to=CTF, value=0, data=redeemPositions_calldata, ...)
    │ внутри Safe: msg.sender = Safe
    ▼
CTF.redeemPositions(collateral, parentCollectionId, conditionId, indexSets)
    │ сжигает токены с msg.sender = Safe
    ▼
CTF переводит USDC → Safe
```

После успеха USDC оказывается на адресе Safe. Для вывода нужна отдельная транзакция `Safe.execTransaction(to=USDC, data=transfer(EOA, amount))` — **но для вашего торгового бота этого делать не нужно**: CLOB и все дальнейшие покупки используют USDC именно с Safe.

---

## 3. Pre-validated signature trick (главный инсайт)

### 3.1 Как работает checkSignatures в Safe

Safe v1.3.0 поддерживает **4 типа подписей**, различаемых по байту `v`:

| v | Тип | Как работает |
|---|-----|-------------|
| 27, 28 (или 31, 32) | ECDSA | Стандартная подпись EIP-712 хеша транзакции |
| 0 | Contract signature (EIP-1271) | Вызов `isValidSignature` на контракте-owner-e |
| 1 | **Pre-validated** | Либо `approvedHashes[owner][hash] != 0`, либо **`msg.sender == owner`** |
| прочие | ethSign | Персональная подпись `\x19Ethereum Signed Message:\n32` |

Именно тип `1` нам и нужен. Код из GnosisSafe.sol:

```solidity
if (v == 1) {
    // If v is 1 then it is an approved hash
    currentOwner = address(uint160(uint256(r)));
    require(
        msg.sender == currentOwner || approvedHashes[currentOwner][dataHash] != 0,
        "GS025"
    );
}
```

Ключевая строка: **`msg.sender == currentOwner`**. Если вы отправляете `execTransaction` от имени owner-а (EOA), то подпись автоматически считается валидной без реальной криптоподписи.

### 3.2 Формат pre-validated signature для execTransaction

Это 65 байт в формате `{r}{s}{v}`:

```
r = 32 bytes = left-padded owner address (0x000000000000000000000000 + 20 bytes EOA)
s = 32 bytes = 0x00...00 (32 нулевых байта)
v = 1 byte  = 0x01
───────────────────────────
total: 65 bytes
```

**В Python (ровно одна строка):**

```python
prevalidated_sig = b'\x00' * 12 + eoa_address_bytes + b'\x00' * 32 + b'\x01'
assert len(prevalidated_sig) == 65
```

Это означает: **никаких EIP-712 хешей, никакой работы с `eth_account.sign_typed_data`, никакой boilerplate** — просто 65 детерминированных байт.

### 3.3 Почему это безопасно

- `msg.sender == currentOwner` проверка → только owner может исполнить транзакцию с такой "подписью"
- Если кто-то другой попытается использовать такую "подпись" — проверка `msg.sender == owner` провалится
- Nonce защищает от replay: каждая `execTransaction` инкрементирует `nonce` в Safe

---

## 4. Путь A vs Путь B — рекомендация

### Путь A — Pre-validated signature (**рекомендован**)

**Плюсы:**
- Минимальный код: ~50 строк, никаких зависимостей кроме `web3`
- Никаких EIP-712 заморочек, ошибиться невозможно
- Никаких `safe-eth-py` (там свои версионные зависимости, иногда конфликтует с современным `web3>=6`)
- Полный контроль: понятно что происходит
- Работает одинаково на всех версиях Safe (0.1.0, 1.0.0, 1.1.0, 1.3.0, 1.4.0)

**Минусы:**
- Нужно вручную собрать ABI для `execTransaction` (7 строк JSON)
- Gas estimation нужно делать самому (но это всё равно просто)

### Путь B — `safe-eth-py`

**Плюсы:**
- Готовая библиотека с методами `Safe.build_multisig_tx(...)`, `.sign()`, `.execute()`
- Умеет работать с Safe Transaction Service для мультисигов (нам не нужно)

**Минусы:**
- Зависимости `safe-eth-py` часто тянут старые версии `web3`, `eth-account`
- Для 1-of-1 это overkill, по сути оборачивает те же 5 вызовов что мы сделаем руками
- У вас `web3>=6` — `safe-eth-py` местами требует pinned версии

### Путь C — Polymarket Relayer API

Полный обход самостоятельного подписывания: Polymarket предоставляет Relayer, которому можно отправлять `executeTx` payload и он исполнит его за нас (gasless). НО:
- Требует **Builder credentials** (`POLY_BUILDER_API_KEY`, `SECRET`, `PASSPHRASE`) — их надо получить на `polymarket.com/settings?tab=builder`
- Требует signature-type EIP-712 на каждую tx
- Добавляет внешнюю зависимость от `relayer.polymarket.com` (если их сервис лежит — вы не редимите)
- Подходит скорее для frontend-интеграций, не для бэкенд-бота

**Вывод: идём Путём A.**

---

## 5. Пошаговая реализация Пути A

### 5.1 Минимальный ABI `execTransaction`

```python
SAFE_EXEC_TX_ABI = [{
    "name": "execTransaction",
    "type": "function",
    "stateMutability": "payable",
    "inputs": [
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "data", "type": "bytes"},
        {"name": "operation", "type": "uint8"},
        {"name": "safeTxGas", "type": "uint256"},
        {"name": "baseGas", "type": "uint256"},
        {"name": "gasPrice", "type": "uint256"},
        {"name": "gasToken", "type": "address"},
        {"name": "refundReceiver", "type": "address"},
        {"name": "signatures", "type": "bytes"},
    ],
    "outputs": [{"name": "success", "type": "bool"}],
}]

SAFE_NONCE_ABI = [{
    "name": "nonce", "type": "function", "stateMutability": "view",
    "inputs": [], "outputs": [{"name": "", "type": "uint256"}],
}]

SAFE_GET_OWNERS_ABI = [{
    "name": "getOwners", "type": "function", "stateMutability": "view",
    "inputs": [], "outputs": [{"name": "", "type": "address[]"}],
}]

CTF_REDEEM_ABI = [{
    "name": "redeemPositions", "type": "function", "stateMutability": "nonpayable",
    "inputs": [
        {"name": "collateralToken", "type": "address"},
        {"name": "parentCollectionId", "type": "bytes32"},
        {"name": "conditionId", "type": "bytes32"},
        {"name": "indexSets", "type": "uint256[]"},
    ],
    "outputs": [],
}]
```

### 5.2 Эталонная реализация SafeExecutor

```python
# src/binance_detector/execution/safe_executor.py
from web3 import Web3
from eth_account import Account
from eth_utils import to_bytes, to_checksum_address

class SafeExecutor:
    def __init__(self, w3: Web3, safe_address: str, eoa_private_key: str):
        self.w3 = w3
        self.safe_address = to_checksum_address(safe_address)
        self.account = Account.from_key(eoa_private_key)
        self.eoa_address = self.account.address

        # minimal Safe ABI
        abi = SAFE_EXEC_TX_ABI + SAFE_NONCE_ABI + SAFE_GET_OWNERS_ABI
        self.safe = w3.eth.contract(address=self.safe_address, abi=abi)

    def is_available(self) -> bool:
        """True если мы owner этого Safe."""
        try:
            owners = self.safe.functions.getOwners().call()
            return any(
                to_checksum_address(o) == self.eoa_address for o in owners
            )
        except Exception:
            return False

    @staticmethod
    def _prevalidated_signature(owner: str) -> bytes:
        """
        65-byte pre-validated signature (v=1).
        Works only when msg.sender == owner.
        """
        owner_bytes = to_bytes(hexstr=owner)  # 20 bytes
        r = b'\x00' * 12 + owner_bytes        # left-pad to 32
        s = b'\x00' * 32
        v = b'\x01'
        sig = r + s + v
        assert len(sig) == 65
        return sig

    def execute(self, to: str, data: bytes, value: int = 0) -> str:
        """
        Исполняет произвольный calldata через Safe. Возвращает tx_hash.
        operation=0 (CALL), все refund-параметры = 0 (без GSN).
        """
        to = to_checksum_address(to)
        signatures = self._prevalidated_signature(self.eoa_address)

        tx = self.safe.functions.execTransaction(
            to,             # to
            value,          # value
            data,           # data
            0,              # operation = 0 (CALL, not DELEGATECALL)
            0,              # safeTxGas
            0,              # baseGas
            0,              # gasPrice (refund in ETH; 0 = no refund)
            "0x0000000000000000000000000000000000000000",  # gasToken
            "0x0000000000000000000000000000000000000000",  # refundReceiver
            signatures,
        ).build_transaction({
            "from": self.eoa_address,
            "nonce": self.w3.eth.get_transaction_count(self.eoa_address),
            "maxFeePerGas": int(self.w3.eth.gas_price * 2),
            "maxPriorityFeePerGas": self.w3.to_wei(30, "gwei"),
            # gas оценивает web3 автоматически, но можно захардкодить:
            # "gas": 400_000,
        })

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()
```

### 5.3 Использование для redeemPositions

```python
# в LiveRedeemService:
ctf_contract = w3.eth.contract(address=CTF_ADDRESS, abi=CTF_REDEEM_ABI)
calldata = ctf_contract.encode_abi(
    "redeemPositions",
    args=[
        USDC_E_ADDRESS,                                # collateralToken
        b'\x00' * 32,                                  # parentCollectionId = bytes32(0)
        bytes.fromhex(condition_id.removeprefix("0x")),  # conditionId
        [1, 2],                                        # indexSets: [YES=1, NO=2]
    ],
)

tx_hash = safe_executor.execute(to=CTF_ADDRESS, data=calldata)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
assert receipt.status == 1
```

**⚠️ NegRisk рынки** — для neg-risk рынков вместо CTF используется **NegRiskAdapter** (`0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296`), у которого свой `redeemPositions`. Нужно определять по `market.negRisk` из Gamma API и подставлять правильный контракт и calldata. Для `btc-updown-5m-*` это обычные binary markets → использовать CTF напрямую.

### 5.4 Критерий R1 completed

Запустить такой тест:
```python
safe = SafeExecutor(w3, PM_FUNDER_ADDRESS, PRIVATE_KEY)
assert safe.is_available(), "EOA не owner этого Safe"
print("Owners:", safe.safe.functions.getOwners().call())
print("Nonce:", safe.safe.functions.nonce().call())
print("OK: R1 passed")
```

Если это проходит — значит Safe стандартный, вы owner, и можно переходить к R2.

---

## 6. Что проверить на вашей конкретной конфигурации ПЕРЕД R2

1. **Verify bytecode:** `w3.eth.get_code(PM_FUNDER_ADDRESS)` должен возвращать минимальный proxy bytecode (~66 байт, начинается с `0x608060...` или `0x3d3d...`). Если пусто — Safe ещё не задеплоен.
2. **VERSION:** вызов `VERSION()` (selector `0xffa1ad74`) должен вернуть строку `"1.3.0"`. Если вернулось что-то другое (например `"1.4.1"`) — формат подписи тот же, работать будет.
3. **Threshold = 1:** `getThreshold()` должен вернуть `1`. Если `>1` — сюрприз, нужно пересмотреть (но для Polymarket всегда 1).
4. **Вы owner:** `getOwners()` должен содержать ваш EOA (с учётом checksum).

Если **любой** из пунктов не сходится — остановитесь и скажите мне результат, это изменит план.

---

## 7. Возможные подводные камни

### 7.1 NegRisk vs обычный CTF
Для neg-risk рынков (`market.negRisk == True` в Gamma) `redeemPositions` нужно вызывать на **NegRiskAdapter**, не на CTF. ABI идентичный, но адрес контракта другой. Проверяйте флаг из API.

### 7.2 conditionId vs marketId
`conditionId` — это `bytes32`, который используется в CTF (и указан в поле `conditionId` или `condition_id` в Gamma API). Это **не** slug и не `market_id`. Для btc-updown это хеш из market-ответа CLOB.

### 7.3 indexSets
Для binary YES/NO рынков:
- `indexSets = [1, 2]` — редим обеих сторон (если держите обе, маловероятно)
- `indexSets = [1]` — только YES
- `indexSets = [2]` — только NO

**Практический совет:** передавайте `[1, 2]` всегда — если одной стороны нет на балансе, CTF просто ничего с ней не сделает и потратит минимум газа. Это проще чем проверять какая сторона выиграла.

### 7.4 payoutNumerators
Перед попыткой редима полезно проверить `ctf.functions.payoutNumerators(conditionId, 0)` — если возвращает 0 и 0, рынок ещё не resolved оракулом. Это и есть ваш E4 в roadmap.

### 7.5 Gas estimation на Polygon
На Polygon нередко `eth_estimateGas` возвращает слишком маленький газ на transactions через Safe из-за внутренних refund-паттернов. Рекомендация:
- Для `execTransaction(redeemPositions)` хардкодить `gas: 500_000` — этого с запасом хватит
- `maxPriorityFeePerGas`: **минимум 30 gwei**, сейчас на Polygon часто требуется 30-50 gwei чтобы транзакция майнилась в разумное время
- `maxFeePerGas`: `base_fee * 2 + maxPriorityFeePerGas` или просто `gas_price * 2`

### 7.6 Nonce Safe vs Nonce EOA
**Две разные переменные**:
- `eth.get_transaction_count(EOA)` — EVM nonce, идёт в build_transaction
- `safe.functions.nonce().call()` — внутренний nonce Safe, нужен только если вы сами считаете EIP-712 hash (для pre-validated signature — НЕ нужен, Safe сам берёт свой nonce)

Для pre-validated signature достаточно EVM nonce.

---

## 8. Итоговая рекомендация

**Путь: A (pre-validated signature, самописный SafeExecutor на web3.py).**

**Обоснование:**
1. Safe стандартный → трюк с v=1 работает гарантированно
2. Единственный owner = наш EOA → `msg.sender == owner` выполнится
3. Простота: 50 строк кода, 0 новых зависимостей
4. Полный контроль: можно легко добавить retry, gas tuning, логирование на каждой стадии
5. Safe-eth-py не нужен и может создать проблемы с версиями

**Следующий шаг:** начать R2 с реализации `SafeExecutor.is_available()` и test-run `getOwners()` через Safe — это займёт ~30 минут и сразу подтвердит всю архитектуру. Редактировать `pyproject.toml` не нужно (никаких новых зависимостей).

---

## 9. Источники

| Источник | Использовано для |
|----------|-----------------|
| docs.polymarket.com/developers/proxy-wallet | Подтверждение: Gnosis Safe для MetaMask |
| github.com/Polymarket/examples | Подтверждение: "slightly modified Gnosis safe, 1-of-1 multisig" |
| github.com/Polymarket/safe-wallet-integration | Factory address, deriveSafe метод |
| polygonscan.com/address/0xaacfeea0... | Исходники Polymarket Safe Proxy Factory (GnosisSafe v1.3.0) |
| polygonscan.com/address/0x4d97dcd9... | CTF ABI для redeemPositions |
| docs.safe.global/advanced/smart-account-signatures | Формат pre-validated signature (v=1) |
| github.com/0-don/polymarket-wallet-recovery | Живой рабочий пример Safe-редима (TS) |
| github.com/Polymarket/py-clob-client/issues/139 | Подтверждение: прямой redeem не работает, нужен execTransaction |
| github.com/Polymarket/conditional-token-examples-py/issues/1 | То же самое для Python SDK |
| medium.com/@cizeon/gnosis-safe-internals-part-3 | Разбор execTransaction параметров |
