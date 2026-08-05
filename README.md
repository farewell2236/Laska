# IIDX SP☆12 OPTION MANAGER

SP☆12のノマゲ・ハード難易度表ごとに使用オプションを記録する静的Webアプリです。

## 最初の動作確認

1. このプロジェクト一式をGitHubの公開リポジトリへアップロードします。
2. `Actions` タブを開きます。
3. `Update difficulty data` を選び、`Run workflow` を実行します。
4. 緑のチェックで完了したら、`data/songs.js` と `data/songs.json` が更新されます。
5. `Settings → Pages` で次を選択します。
   - Source: `Deploy from a branch`
   - Branch: `main`
   - Folder: `/(root)`
6. 表示されたGitHub Pages URLを開きます。

## ローカル確認

Actions実行後にリポジトリをZIPでダウンロードし、`index.html` をChromeで直接開けます。

画面は `data/songs.js` を通常のscriptとして読み込むため、`file://` でもCORSエラーになりません。
初期状態のZIPには空データしか入っていないため、先にGitHub Actionsを1回実行してください。

## データ参照先

- ノマゲ: `https://iidx-difficulty-table-checker.nomadblacky.dev/table/12_normal`
- ハード: `https://iidx-difficulty-table-checker.nomadblacky.dev/table/12_hard`

## 自動更新

毎週月曜日にGitHub Actionsが難易度表を確認します。手動実行も可能です。

## 保存

使用オプションはブラウザのLocalStorageに保存されます。別端末へ移す場合は、画面の「バックアップ保存」「バックアップ読込」を使ってください。
