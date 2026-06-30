import sys, json, re, os, time, urllib.request
from datetime import datetime, timedelta, timezone

# グローバル変数
info_data = {}
sleep_time = 2
now_jst = ""

# ==========================================
# 関数定義エリア
# ==========================================
def convert_time(time_str):
    if not time_str: return ""
    time_str = re.sub(r'\s+', ' ', time_str.strip())
    time_str_upper = time_str.replace('am', 'AM').replace('pm', 'PM')
    
    try: # 英語フォーマット
        dt = datetime.strptime(time_str_upper, "%b %d, %Y %I:%M%p")
        dt += timedelta(hours=9)
        return dt.strftime("%Y/%m/%d %H:%M:%S")
    except ValueError: pass
    
    try: # 日本語フォーマット(年省略)
        dt = datetime.strptime(time_str, "%m/%d %H:%M")
        dt += timedelta(hours=9)
        return dt.strftime("%m/%d %H:%M")
    except ValueError: pass
    
    return time_str

def fetch_markdown(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        # timeout=None でタイムアウトを無効化（無期限待機）
        with urllib.request.urlopen(req, timeout=None) as res:
            return res.read().decode('utf-8'), None
    except Exception as e:
        return None, str(e)

def process_padlet(url, path, is_info):
    global info_data, sleep_time, now_jst
    
    # KEYの生成 (例: archive/nyg/main.md -> nyg/main)
    key = path.replace("archive/", "").replace(".md", "")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    valid_fetch = False
    content = ""
    
    # 最大2回試行するループ（1回目がダメならもう一度だけやり直す）
    for attempt in range(1, 3):
        content, error_msg = fetch_markdown(url)
        
        # エラー原因の判定
        if error_msg is not None:
            err_type = f"通信・取得失敗 ({error_msg})"
        elif not content.strip():
            err_type = "データが空白"
        elif content.startswith("<!DOCTYPE html>"):
            err_type = "エラーページ(HTML)"
        else:
            err_type = None # 正常に取得できた場合
            
        # 正常に取得できたらループを抜ける
        if err_type is None:
            valid_fetch = True
            break
            
        # 1回目でエラーが発生した場合はすぐにリトライ
        if attempt == 1:
            print(f"⚠️ {path} の1回目の取得で問題が発生しました（原因: {err_type}）。すぐに一度だけやり直します...")
        else:
            # 2回目もダメだった場合は、最終的なエラー理由を確定して出力
            if error_msg is not None:
                print(f"❌ エラー: {path} の通信・取得に失敗しました ({error_msg})。更新をスキップします。")
            elif not content.strip():
                print(f"⚠️ エラー: {path} はデータが空白でした。更新をスキップします。")
            elif content.startswith("<!DOCTYPE html>"):
                print(f"⚠️ スキップ: {path} はエラーページ(HTML)でした。更新しません。")

    # 2. 正常に取得できた場合のみ、差分チェックと保存を行う
    if valid_fetch:
        changed = True
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.read().split('\n')
                existing_body = '\n'.join(lines[2:]).strip()
            if existing_body == content.strip():
                if is_info:
                    print(f"✅ 変更なし: {path}")
                else:
                    print(f"✅ 変更なし(info除外): {path}")
                changed = False
        
        if changed:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f"最終取得: {now_jst}\n\n{content}")
            if is_info:
                print(f"🔄 更新完了: {path} ({now_jst})")
            else:
                print(f"🔄 更新完了(info除外): {path} ({now_jst})")

    # 3. info.json の構築（エラーで更新されなかった場合も、既存ファイルから情報を復活させる）
    if is_info and os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            saved_lines = [line.strip() for line in f.read().split('\n')]
            
        fetched = saved_lines[0].replace("最終取得: ", "").strip() if saved_lines and saved_lines[0].startswith("最終取得: ") else ""
        content_lines = saved_lines[2:] if len(saved_lines) > 2 else []
        
        title = content_lines[0][2:] if content_lines and content_lines[0].startswith('# ') else ""
        desc, link, builder, posts, created, updated = "", "", "", "0", "", ""
        
        for line in content_lines[1:10]:
            if line == "": continue
            if line.startswith('## '): break
            desc = line
            break
            
        for line in content_lines[:20]:
            m_link = re.search(r'\*\*(?:Link|リンク):\*\*\s*(.*)', line)
            if m_link: link = m_link.group(1)
            
            m_builder = re.search(r'\*\*(?:Builder|所有者):\*\*\s*(.*)', line)
            if m_builder: builder = m_builder.group(1)
            
            m_posts = re.search(r'\*\*(?:Posts|投稿):\*\*\s*(.*)', line)
            if m_posts: posts = m_posts.group(1)
            
            m_created = re.search(r'\*\*(?:Created At \(UTC\)|作成日（UTC）):\*\*\s*(.*)', line)
            if m_created: created = convert_time(m_created.group(1))
            
            m_updated = re.search(r'\*\*(?:Updated At \(UTC\)|更新日（UTC）):\*\*\s*(.*)', line)
            if m_updated: updated = convert_time(m_updated.group(1))
            
        try:
            posts = int(posts)
        except ValueError:
            pass

        # 実行された順番に辞書に追加されていく
        info_data[key] = {
            "title": title,
            "desc": desc,
            "link": link,
            "builder": builder,
            "posts": posts,
            "created": created,
            "updated": updated,
            "fetched": fetched
        }
        
    time.sleep(sleep_time)

# info.jsonに入れる用
def save_padlet(url, path):
    process_padlet(url, path, is_info=True)

# info.jsonに入れない用
def save_padlet2(url, path):
    process_padlet(url, path, is_info=False)


# ==========================================
# メイン処理
# ==========================================
if __name__ == '__main__':
    # 引数からイベント名を取得し、待機時間を決める
    event_name = sys.argv[1] if len(sys.argv) > 1 else "schedule"
    sleep_time = 1 if event_name == "workflow_dispatch" else 2
    
    print(f"現在のモード: {event_name}")
    print(f"待機時間: {sleep_time}秒\n")

    # JST時刻の準備
    JST = timezone(timedelta(hours=+9), 'JST')
    now_jst = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

    # ==========================================
    # 実行エリア（ここから下を自由に編集してください）
    # ==========================================

    # --- 1. nyg シリーズ ---
    save_padlet("https://padlet.com/padlets/a8v7cjbbfni702kg/exports/markdown.md", "archive/nyg/main.md")
    save_padlet("https://padlet.com/padlets/scvs0iw7tdatft21/exports/markdown.md", "archive/nyg/archive.md")
    save_padlet("https://padlet.com/padlets/ybtryru0lgzpxp34/exports/markdown.md", "archive/nyg/ssjc.md")
    save_padlet("https://padlet.com/padlets/lpiw7xio9gwnmxrd/exports/markdown.md", "archive/nyg/portalworld.md")
    save_padlet("https://padlet.com/padlets/i0fd897smvjo0tvj/exports/markdown.md", "archive/nyg/arashitaisaku.md")
    save_padlet("https://padlet.com/padlets/4b9092979b4e6dlm/exports/markdown.md", "archive/nyg/games.md")
    save_padlet("https://padlet.com/padlets/hqm4zg0lw3smlc23/exports/markdown.md", "archive/nyg/ssjt2025.md")

    # --- 2. woolisbest シリーズ ---
    save_padlet("https://padlet.com/padlets/99xq7bb7zjzcfzw0/exports/markdown.md", "archive/woolisbest/lobby.md")
    save_padlet("https://padlet.com/padlets/f46agi7nbsmz8boy/exports/markdown.md", "archive/woolisbest/main.md")

    # --- 3. magurock シリーズ ---
    save_padlet("https://padlet.com/padlets/e9n4zhdx6ucfbaa4/exports/markdown.md", "archive/magurock/lobby.md")
    save_padlet("https://padlet.com/padlets/v7eblregk0t2eq0k/exports/markdown.md", "archive/magurock/main.md")

    # --- 4. kiseikaijoiinkai シリーズ (info.json除外) ---
    save_padlet2("https://padlet.com/padlets/5db70e80bto7rnxl/exports/markdown.md", "archive/kiseikaijoiinkai/lobby.md")
    save_padlet2("https://padlet.com/padlets/g07iihoi22rh2q7l/exports/markdown.md", "archive/kiseikaijoiinkai/main.md")

    # --- 5. その他の単独ファイル ---
    save_padlet("https://padlet.com/padlets/n0g1c0jl2ak3grc5/exports/markdown.md", "archive/sennin.md")
    save_padlet("https://padlet.com/padlets/zsdegt1d6scuq9qa/exports/markdown.md", "archive/beruri.md")
    save_padlet("https://padlet.com/padlets/afg5jcs1w4yyk2h1/exports/markdown.md", "archive/hikari.md")
    save_padlet("https://padlet.com/padlets/kulz2hpe9vtrxep4/exports/markdown.md", "archive/itrsa.md")
    save_padlet("https://padlet.com/padlets/34b6kq9lghbe3rtm/exports/markdown.md", "archive/kabotya.md")
    save_padlet("https://padlet.com/padlets/5ggicyna1yjvquxr/exports/markdown.md", "archive/obungu.md")
    save_padlet("https://padlet.com/padlets/236elh6xnvi2nw9q/exports/markdown.md", "archive/romanpearce.md")
    save_padlet("https://padlet.com/padlets/fj7pwrjfd44519fq/exports/markdown.md", "archive/bonjour.md")
    save_padlet2("https://padlet.com/padlets/okjy1jmzjzdbb5jm/exports/markdown.md", "archive/ouga.md")

    # ==========================================
    # JSON一括書き出し
    # ==========================================
    print("\n🔄 info.json を構築しています...")
    if info_data:
        with open('info.json', 'w', encoding='utf-8') as f:
            json.dump(info_data, f, ensure_ascii=False, indent=2)
        print("✅ info.json の構築が完了しました。")
    else:
        print("⚠️ info.json に追加するデータがありませんでした。")
