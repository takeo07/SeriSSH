# SeriSSH

軽量な SSH -> PTY/シリアル ブリッジ（WSL/Linux向け、Python実装）

概要
- SSH 接続を受け付け、SSH セッションの PTY とシリアル用 PTY または指定したシリアルデバイスを双方向で中継します。

セットアップ

依存関係をインストールします:

```bash
python -m pip install -r requirements.txt
```

起動例（テスト用のユーザー/パスワード認証）:

```bash
python -m src.seri_ssh.cli --port 2222 --user test --password secret
```

物理シリアルデバイス（例: /dev/ttyUSB0）を直接ブリッジする場合:

```bash
python -m src.seri_ssh.cli --port 2222 --user test --password secret --serial /dev/ttyUSB0
```

シリアル PTY を作成するモード（--serial 未指定）では、作成される slave 側のデバイスパスをログ出力します。

接続方法（クライアント）:

```bash
ssh -p 2222 test@localhost
```

注意
- 現状は簡易実装です。公開環境での運用前に認証や鍵管理を強化してください。
# SeriSSH
