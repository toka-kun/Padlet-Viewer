import sys, json, re, os, time, urllib.request
from datetime import datetime, timedelta, timezone

# グローバル変数
info_data = {}
sleep_time = 2
now_jst = ""
now_jst_dt = None

# ==========================================
# 設定
# ==========================================
ANALYTICS_MODE = os.environ.get('ANALYTICS', '1') != '0'   # ANALYTICS=0 で統計取得を止める
CSV_DIR = "archive"
RE_HASHID = re.compile(r'wall_hashid=(board_[A-Za-z0-9]+)')
RE_WALLID = re.compile(r'"wallId":\s*"?(\d+)')

# ==========================================
# ボードID一覧（ここだけ編集すればOK）
#   (ボードID, 保存名)  保存名は archive/<保存名>/ 配下に展開される
# ==========================================
BOARDS = [
    ("a8v7cjbbfni702kg", "nyg/main"),
    ("scvs0iw7tdatft21", "nyg/archive"),
    ("ybtryru0lgzpxp34", "nyg/ssjc"),
    ("lpiw7xio9gwnmxrd", "nyg/portalworld"),
    ("i0fd897smvjo0tvj", "nyg/arashitaisaku"),
    ("4b9092979b4e6dlm", "nyg/games"),
    ("hqm4zg0lw3smlc23", "nyg/ssjt2025"),
    ("99xq7bb7zjzcfzw0", "woolisbest/lobby"),
    ("f46agi7nbsmz8boy", "woolisbest/main"),
    ("e9n4zhdx6ucfbaa4", "magurock/lobby"),
    ("v7eblregk0t2eq0k", "magurock/main"),
    ("n0g1c0jl2ak3grc5", "sennin"),
    ("zsdegt1d6scuq9qa", "beruri"),
    ("afg5jcs1w4yyk2h1", "hikari"),
    ("kulz2hpe9vtrxep4", "itrsa"),
    ("34b6kq9lghbe3rtm", "kabotya"),
    ("5ggicyna1yjvquxr", "obungu"),
    ("236elh6xnvi2nw9q", "romanpearce"),
    ("fj7pwrjfd44519fq", "bonjour"),
]

# info.json には入れないボード（md と 統計CSV は保存する）
BOARDS_NO_INFO = [
    ("5db70e80bto7rnxl", "kiseikaijoiinkai/lobby"),
    ("g07iihoi22rh2q7l", "kiseikaijoiinkai/main"),
    ("okjy1jmzjzdbb5jm", "ouga"),
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
        # timeout=None でタイムアウトを無効化（無期限待機）
        with urllib.request.urlopen(req, timeout=None) as res:
            return res.read().decode('utf-8'), None
    except Exception as e:
        return None, str(e)


def fetch_text(url, timeout=30):
    """HTML/JSONを文字列で取る（統計取得用）"""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.read().decode('utf-8', 'replace'), None
    except Exception as e:
        return None, str(e)


def build_md_url(board_id):
    """ボードIDからマークダウンのエクスポートURLを組み立てる"""
    return f"https://padlet.com/padlets/{board_id}/exports/markdown.md"


def build_fallback_url(board_id):
    """mdが取れなかったときにinfo.jsonへ入れるURL"""
    return f"https://padlet.com/padlets/{board_id}"


def resolve_ids(board_id):
    """ボードID -> (hashid, wall_id)
    /padlets/{id} は301で正規URL(/{ns}/padlet-{id})へ飛ぶので、そのHTMLから抜く。
      - board_xxxx   : <link rel="preload" id="wishes-preload" href="...wall_hashid=board_xxx...">
      - wallId       : "wallId":"123456789"
    """
    html, err = fetch_text(f"https://padlet.com/padlets/{board_id}")
    if not html:
        return None, None
    m = RE_HASHID.search(html)
    hashid = m.group(1) if m else None
    w = RE_WALLID.search(html)
    wall_id = int(w.group(1)) if w else None
    return hashid, wall_id


def fetch_analytics(board_id, cache):
    """pageviews / visitors / engagementTimeMin を取得。失敗時は None。"""
    empty = {"pageviews": None, "visitors": None, "engagementTimeMin": None}
    if not ANALYTICS_MODE:
        return empty
    if board_id in cache:
        return cache[board_id]

    hashid, wall_id = resolve_ids(board_id)
    if not hashid:
        cache[board_id] = empty
        return empty

    for attempt in range(1, 4):
        js, err = fetch_text(f"https://padlet.com/api/9/walls/{hashid}/analytics")
        if js:
            try:
                a = json.loads(js)['data']['attributes']
                out = {
                    "pageviews": a.get("pageviews"),
                    "visitors": a.get("visitors"),
                    "engagementTimeMin": a.get("engagementTimeMin"),
                }
                out["hashid"] = hashid
                out["wall_id"] = wall_id
                cache[board_id] = out
                return out
            except Exception:
                pass
        time.sleep(2 * attempt)   # 429対策のバックオフ

    cache[board_id] = empty
    return empty


def update_csv(csv_path, ts_str, row):
    """秒単位の統計をCSVへ1行追記する（同じ秒なら上書き）。古い順に並べる。"""
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    header = ["datetime", "year_month", "pageviews", "visitors", "engagementTimeMin", "posts", "title"]
    rows = []
    if os.path.exists(csv_path):
        with open(csv_path, 'r', encoding='utf-8', newline='') as f:
            lines = f.read().splitlines()
        if lines and lines[0].split(',')[0] in ("datetime", "date"):
            header = lines[0].split(',')      # 既存ヘッダーを尊重
            rows = lines[1:]

    ym = ts_str[:7].replace('-', '')          # 2026-11-18 15:18:12 -> 202611
    new_row = [ts_str, ym] + [str(row.get(h, "")) for h in header[2:]]

    # 同じタイムスタンプ（秒まで一致）の行があれば置換、なければ追加
    out, replaced = [], False
    for r in rows:
        if r.split(',')[0] == ts_str:
            out.append(','.join(new_row)); replaced = True
        else:
            out.append(r)
    if not replaced:
        out.append(','.join(new_row))

    # タイムスタンプで古い順にソート（秒あり／秒なし両対応）
    def sort_key(r):
        v = r.split(',')[0]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try: return datetime.strptime(v, fmt)
            except Exception: pass
        return datetime.max
    out.sort(key=sort_key)

    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        f.write(','.join(header) + '\n')
        for r in out:
            f.write(r + '\n')
    return len(out)


def parse_md_info(md_path):
    """保存済みのREADME.mdからタイトル・説明・リンク等を読み取る。
    mdが無い場合は空の値を返す（info.jsonに入れないボードでもタイトルは使う）。"""
    empty = {"title": "", "desc": "", "link": "", "builder": "",
             "posts": 0, "created": "", "updated": "", "fetched": ""}
    if not os.path.exists(md_path):
        return empty

    with open(md_path, 'r', encoding='utf-8') as f:
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

    summary_start = None
    summary_end = len(content_lines)
    for i, line in enumerate(content_lines):
        if summary_start is None:
            if re.match(r'^##\s+(?:Summary|要約)\s*$', line):
                summary_start = i + 1
            continue
        if line.startswith('## '):
            summary_end = i
            break
    summary_lines = content_lines[summary_start:summary_end] if summary_start is not None else []

    for line in summary_lines:
        m_link = re.search(r'\*\*(?:Link|リンク):\*\*\s*(.*)', line)
        if m_link: link = m_link.group(1)

        m_builder = re.search(r'\*\*(?:Builder|所有者):\*\*\s*(.*)', line)
        if m_builder: builder = m_builder.group(1)

        m_posts = re.search(r'\*\*(?:Posts|投稿):\*\*\s*(.*)', line)
        if m_posts: posts = m_posts.group(1)

        m_created = re.search(r'\*\*(?:Created At|作成日)(?:\s*[\(（]UTC[\)）])?:\*\*\s*(.*)', line)
        if m_created: created = convert_time(m_created.group(1))

        m_updated = re.search(r'\*\*(?:Updated At|更新日)(?:\s*[\(（]UTC[\)）])?:\*\*\s*(.*)', line)
        if m_updated: updated = convert_time(m_updated.group(1))

    try:
        posts = int(posts)
    except ValueError:
        pass

    return {"title": title, "desc": desc, "link": link, "builder": builder,
            "posts": posts, "created": created, "updated": updated, "fetched": fetched}


def process_padlet(board_id, name, is_info, ana_cache):
    global info_data, sleep_time, now_jst, now_jst_dt

    key = name                                        # 例: nyg/main
    md_url = build_md_url(board_id)
    md_path = os.path.join(CSV_DIR, name, "README.md")  # 例: archive/nyg/main/README.md
    os.makedirs(os.path.dirname(md_path), exist_ok=True)

    valid_fetch = False
    content = ""

    # 最大2回試行するループ
    for attempt in range(1, 3):
        content, error_msg = fetch_markdown(md_url)

        if error_msg is not None:
            err_type = f"通信・取得失敗 ({error_msg})"
        elif not content.strip():
            err_type = "データが空白"
        elif content.startswith("<!DOCTYPE html>"):
            err_type = "エラーページ(HTML)"
        else:
            err_type = None

        if err_type is None:
            valid_fetch = True
            break

        if attempt == 1:
            print(f"⚠️ {name} の1回目の取得で問題が発生しました（原因: {err_type}）。すぐに一度だけやり直します...")
        else:
            if error_msg is not None:
                print(f"❌ エラー: {name} の通信・取得に失敗しました ({error_msg})。更新をスキップします。")
            elif not content.strip():
                print(f"⚠️ エラー: {name} はデータが空白でした。更新をスキップします。")
            elif content.startswith("<!DOCTYPE html>"):
                print(f"⚠️ スキップ: {name} はエラーページ(HTML)でした。更新しません。")

    # 2. 差分チェックと保存
    if valid_fetch:
        changed = True
        if os.path.exists(md_path):
            with open(md_path, 'r', encoding='utf-8') as f:
                lines = f.read().split('\n')
                existing_body = '\n'.join(lines[2:]).strip()
            if existing_body == content.strip():
                if is_info:
                    print(f"✅ 変更なし: {md_path}")
                else:
                    print(f"✅ 変更なし(info除外): {md_path}")
                changed = False

        if changed:
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(f"最終取得: {now_jst}\n\n{content}")
            if is_info:
                print(f"🔄 更新完了: {md_path} ({now_jst})")
            else:
                print(f"🔄 更新完了(info除外): {md_path} ({now_jst})")

    # 3. mdからメタ情報を読み取る（info.jsonに入れないボードでも使う）
    meta = parse_md_info(md_path)

    # 4. 統計値の取得とCSV保存（is_info に関係なく必ず実行）
    ana = fetch_analytics(board_id, ana_cache)

    if not valid_fetch and not meta["link"]:
        meta["link"] = build_fallback_url(board_id)

    if ana.get("pageviews") is not None:
        csv_path = os.path.join(CSV_DIR, name,
                                now_jst_dt.strftime("%Y"),
                                now_jst_dt.strftime("%m") + ".csv")
        ts_str = now_jst_dt.strftime("%Y-%m-%d %H:%M:%S")
        n = update_csv(csv_path, ts_str, {
            "pageviews": ana.get("pageviews"),
            "visitors": ana.get("visitors"),
            "engagementTimeMin": ana.get("engagementTimeMin"),
            "posts": meta["posts"],
            "title": meta["title"],
        })
        tag = "" if is_info else "(info除外)"
        print(f"📊 {name}{tag}: PV={ana['pageviews']:,} / UU={ana['visitors']:,} / "
              f"滞在={ana['engagementTimeMin']}分 → {csv_path} ({n}行)")
    else:
        print(f"ℹ️ {name}: 統計値は取得できませんでした（非公開/削除済み）")

    # 5. info.json への追加（is_info のときだけ）
    if not is_info:
        time.sleep(sleep_time)
        return

    if os.path.exists(md_path):
        info_data[key] = {
            "title": meta["title"],
            "desc": meta["desc"],
            "link": meta["link"],
            "builder": meta["builder"],
            "posts": meta["posts"],
            "created": meta["created"],
            "updated": meta["updated"],
            "fetched": meta["fetched"],
            "pageviews": ana.get("pageviews"),
            "visitors": ana.get("visitors"),
            "engagementTimeMin": ana.get("engagementTimeMin"),
            "board_id": board_id,
            "hashid": ana.get("hashid"),
        }
    else:
        # mdが一度も取れていない場合も、info.jsonにURLだけは載せる
        info_data[key] = {
            "title": "", "desc": "", "link": build_fallback_url(board_id),
            "builder": "", "posts": 0, "created": "", "updated": "", "fetched": "",
            "pageviews": ana.get("pageviews"),
            "visitors": ana.get("visitors"),
            "engagementTimeMin": ana.get("engagementTimeMin"),
            "board_id": board_id, "hashid": ana.get("hashid"),
        }
        print(f"📝 {name}: md未取得のためURLのみ登録 ({build_fallback_url(board_id)})")

    time.sleep(sleep_time)


# info.jsonに入れる用
def save_padlet(board_id, name):
    process_padlet(board_id, name, is_info=True, ana_cache=ANA_CACHE)

# info.jsonに入れない用
def save_padlet2(board_id, name):
    process_padlet(board_id, name, is_info=False, ana_cache=ANA_CACHE)


ANA_CACHE = {}


# ==========================================
# メイン処理
# ==========================================
if __name__ == '__main__':
    # 引数からイベント名を取得し、待機時間を決める
    event_name = sys.argv[1] if len(sys.argv) > 1 else "schedule"
    sleep_time = 1 if event_name == "workflow_dispatch" else 2

    print(f"現在のモード: {event_name}")
    print(f"待機時間: {sleep_time}秒")
    print(f"統計取得: {'有効' if ANALYTICS_MODE else '無効'}\n")

    # JST時刻の準備
    JST = timezone(timedelta(hours=+9), 'JST')
    now_jst_dt = datetime.now(JST)
    now_jst = now_jst_dt.strftime("%Y/%m/%d %H:%M:%S")

    # ==========================================
    # 実行エリア
    # ==========================================
    for board_id, name in BOARDS:
        save_padlet(board_id, name)

    for board_id, name in BOARDS_NO_INFO:
        save_padlet2(board_id, name)

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
