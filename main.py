import sys, json, re, os, time, urllib.request
from datetime import datetime, timedelta, timezone

# ==========================================
# 設定エリア：URLリスト
# ==========================================
TARGETS = [
    # --- 1. nyg シリーズ ---
    {"url": "https://padlet.com/padlets/a8v7cjbbfni702kg/exports/markdown.md", "path": "archive/nyg/main.md", "info": True},
    {"url": "https://padlet.com/padlets/scvs0iw7tdatft21/exports/markdown.md", "path": "archive/nyg/archive.md", "info": True},
    {"url": "https://padlet.com/padlets/ybtryru0lgzpxp34/exports/markdown.md", "path": "archive/nyg/ssjc.md", "info": True},
    {"url": "https://padlet.com/padlets/lpiw7xio9gwnmxrd/exports/markdown.md", "path": "archive/nyg/portalworld.md", "info": True},
    {"url": "https://padlet.com/padlets/i0fd897smvjo0tvj/exports/markdown.md", "path": "archive/nyg/arashitaisaku.md", "info": True},
    {"url": "https://padlet.com/padlets/4b9092979b4e6dlm/exports/markdown.md", "path": "archive/nyg/games.md", "info": True},
    {"url": "https://padlet.com/padlets/hqm4zg0lw3smlc23/exports/markdown.md", "path": "archive/nyg/ssjt2025.md", "info": True},

    # --- 2. woolisbest シリーズ ---
    {"url": "https://padlet.com/padlets/99xq7bb7zjzcfzw0/exports/markdown.md", "path": "archive/woolisbest/lobby.md", "info": True},
    {"url": "https://padlet.com/padlets/f46agi7nbsmz8boy/exports/markdown.md", "path": "archive/woolisbest/main.md", "info": True},

    # --- 3. magurock シリーズ ---
    {"url": "https://padlet.com/padlets/e9n4zhdx6ucfbaa4/exports/markdown.md", "path": "archive/magurock/lobby.md", "info": True},
    {"url": "https://padlet.com/padlets/v7eblregk0t2eq0k/exports/markdown.md", "path": "archive/magurock/main.md", "info": True},

    # --- 4. kiseikaijoiinkai シリーズ (info.json除外) ---
    {"url": "https://padlet.com/padlets/5db70e80bto7rnxl/exports/markdown.md", "path": "archive/kiseikaijoiinkai/lobby.md", "info": False},
    {"url": "https://padlet.com/padlets/g07iihoi22rh2q7l/exports/markdown.md", "path": "archive/kiseikaijoiinkai/main.md", "info": False},

    # --- 5. その他の単独ファイル ---
    {"url": "https://padlet.com/padlets/n0g1c0jl2ak3grc5/exports/markdown.md", "path": "archive/sennin.md", "info": True},
    {"url": "https://padlet.com/padlets/zsdegt1d6scuq9qa/exports/markdown.md", "path": "archive/beruri.md", "info": True},
    {"url": "https://padlet.com/padlets/afg5jcs1w4yyk2h1/exports/markdown.md", "path": "archive/hikari.md", "info": True},
    {"url": "https://padlet.com/padlets/kulz2hpe9vtrxep4/exports/markdown.md", "path": "archive/itrsa.md", "info": True},
    {"url": "https://padlet.com/padlets/34b6kq9lghbe3rtm/exports/markdown.md", "path": "archive/kabotya.md", "info": True},
    {"url": "https://padlet.com/padlets/5ggicyna1yjvquxr/exports/markdown.md", "path": "archive/obungu.md", "info": True},
    {"url": "https://padlet.com/padlets/236elh6xnvi2nw9q/exports/markdown.md", "path": "archive/romanpearce.md", "info": True},
    {"url": "https://padlet.com/padlets/fj7pwrjfd44519fq/exports/markdown.md", "path": "archive/bonjour.md", "info": True},
    {"url": "https://padlet.com/padlets/okjy1jmzjzdbb5jm/exports/markdown.md", "path": "archive/ouga.md", "info": False}, # info除外
]

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
        with urllib.request.urlopen(req) as res:
            content = res.read().decode('utf-8')
            return content
    except Exception as e:
        return None

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

    info_data = {}

    for target in TARGETS:
        url = target["url"]
        path = target["path"]
        is_info = target["info"]
        
        # KEYの生成 (例: archive/nyg/main.md -> nyg/main)
        key = path.replace("archive/", "").replace(".md", "")
        
        # フォルダがない場合は作成
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        content = fetch_markdown(url)
        
        if not content or not content.strip():
            print(f"⚠️ エラー: {path} はデータが取得できないか空白でした。スキップします。")
            time.sleep(sleep_time)
            continue
            
        if content.startswith("<!DOCTYPE html>"):
            print(f"⚠️ スキップ: {path} はエラーページ(HTML)でした。更新しません。")
            time.sleep(sleep_time)
            continue
            
        # 差分チェック
        changed = True
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.read().split('\n')
                # 既存ファイルのヘッダー（1,2行目）を除外した本文
                existing_body = '\n'.join(lines[2:]).strip()
            if existing_body == content.strip():
                print(f"✅ 変更なし: {path}")
                changed = False
        
        # 変更があれば保存
        if changed:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f"最終取得: {now_jst}\n\n{content}")
            print(f"🔄 更新完了: {path} ({now_jst})")
            
        # info.json 用のデータをパースして収集
        if is_info:
            # 更新されていなくても、info.jsonを再構築するために既存ファイルをパース
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
        
    # 全ての処理が終わったら info.json を書き出し
    print("🔄 info.json を構築しています...")
    if info_data:
        with open('info.json', 'w', encoding='utf-8') as f:
            json.dump(info_data, f, ensure_ascii=False, indent=2)
    else:
        print("info.json に追加するデータがありませんでした。")
