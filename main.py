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
POSTS_MODE = os.environ.get('POSTS', '1') != '0'           # POSTS=0 で投稿数のカウントを止める
CSV_DIR = "archive"
RE_HASHID = re.compile(r'wall_hashid=(board_[A-Za-z0-9]+)')
RE_WALLID = re.compile(r'"wallId":\s*"?(\d+)')
RESOLVE_CACHE = {}          # board_id -> (hashid, wall_id)  1実行中は使い回す

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


def convert_iso_time(iso_str):
    """APIのISO8601（UTC, 例 2026-11-19T00:38:21.335Z）を JST の 'YYYY/MM/DD HH:MM:SS' に直す"""
    if not iso_str or not isinstance(iso_str, str):
        return ""
    s = iso_str.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return iso_str
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=9))).strftime("%Y/%m/%d %H:%M:%S")


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
      - wallId       : "wallId":"213015220"
    """
    if board_id in RESOLVE_CACHE:
        return RESOLVE_CACHE[board_id]
    html, err = fetch_text(f"https://padlet.com/padlets/{board_id}")
    if not html:
        return None, None
    m = RE_HASHID.search(html)
    hashid = m.group(1) if m else None
    w = RE_WALLID.search(html)
    wall_id = int(w.group(1)) if w else None
    RESOLVE_CACHE[board_id] = (hashid, wall_id)
    return hashid, wall_id


def fetch_wall_info(hashid):
    """ボード属性を /api/9/walls/{hashid} から取得する（mdより詳細・形式が安定）
    失敗時は None を返す。"""
    for attempt in range(1, 4):
        js, err = fetch_text(f"https://padlet.com/api/9/walls/{hashid}")
        if js:
            try:
                return json.loads(js)['data']
            except Exception:
                pass
        time.sleep(2 * attempt)
    return None


def count_posts(hashid, max_pages=60):
    """投稿数をAPIで数える（1ページ100件 / 331投稿で 4ページ・約3秒）"""
    if not POSTS_MODE:
        return None
    cur = ""
    n = 0
    for _ in range(max_pages):
        js, err = fetch_text(f"https://padlet.com/api/10/wishes?wall_hashid={hashid}&page_start={cur}")
        if not js:
            break
        try:
            d = json.loads(js)
        except Exception:
            break
        n += len(d.get("data", []))
        nxt = (d.get("meta") or {}).get("next")
        if not nxt:
            break
        cur = nxt
        time.sleep(0.15)
    return n or None


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
    header = ["datetime", "year_month", "pageviews", "visitors", "engagementTimeMin",
              "posts", "viz", "is_commentable", "is_reactable", "is_remakeable",
              "is_premium", "created", "updated", "builder", "title", "source"]
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
    """mdから読む（APIが使えないときのフォールバック専用）"""
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
    for line in (content_lines[summary_start:summary_end] if summary_start is not None else []):
        m = re.search(r'\*\*(?:Link|リンク):\*\*\s*(.*)', line)
        if m: link = m.group(1)
        m = re.search(r'\*\*(?:Builder|所有者):\*\*\s*(.*)', line)
        if m: builder = m.group(1)
        m = re.search(r'\*\*(?:Posts|投稿):\*\*\s*(.*)', line)
        if m: posts = m.group(1)
        m = re.search(r'\*\*(?:Created At|作成日)(?:\s*[\(（]UTC[\)）])?:\*\*\s*(.*)', line)
        if m: created = convert_time(m.group(1))
        m = re.search(r'\*\*(?:Updated At|更新日)(?:\s*[\(（]UTC[\)）])?:\*\*\s*(.*)', line)
        if m: updated = convert_time(m.group(1))
    try:
        posts = int(posts)
    except ValueError:
        pass
    return {"title": title, "desc": desc, "link": link, "builder": builder,
            "posts": posts, "created": created, "updated": updated, "fetched": fetched}


def build_meta(board_id, md_path):
    """ボード情報を組み立てる。**API (/api/9/walls/{hashid}) を優先**し、
    失敗したときだけ md にフォールバックする。"""
    md = parse_md_info(md_path)                     # フォールバック用
    hashid = resolve_ids(board_id)[0]

    if not hashid:
        return md, None

    data = fetch_wall_info(hashid)
    if not data:
        return md, hashid

    a = data.get("attributes", {}) or {}
    b = ((a.get("builder") or {}).get("data") or {}).get("attributes") or {}
    links = data.get("links") or {}

    # 作成者名: display_name があれば「表示名 (username)」形式
    bname = b.get("display_name") or b.get("name") or ""
    if bname and b.get("username"):
        builder = f"{bname} ({b['username']})"
    else:
        builder = bname or md["builder"]

    meta = {
        "title": a.get("title") or a.get("name") or md["title"],
        "desc": a.get("description") or "",
        "link": links.get("show") or md["link"] or build_fallback_url(board_id),
        "builder": builder,
        "posts": count_posts(hashid),                # 属性に無いのでAPIで数える（POSTS=0 で省略）
        "created": convert_iso_time(a.get("created_at")),
        "updated": convert_iso_time(a.get("updated_at")),
        "fetched": md["fetched"] or now_jst,
        # --- APIにしか無い項目 ---
        "name": a.get("name", md.get("name")),
        "address": a.get("address", md.get("address")),
        "namespace": a.get("namespace", md.get("namespace")),
        "public_key": a.get("public_key", md.get("public_key")),
        "hashid": a.get("hashid", md.get("hashid")),
        "viz": a.get("viz", md.get("viz")),
        "is_commentable": a.get("is_commentable", md.get("is_commentable")),
        "is_reactable": a.get("is_reactable", md.get("is_reactable")),
        "is_remakeable": a.get("is_remakeable", md.get("is_remakeable")),
        "is_moderated": a.get("is_moderated", md.get("is_moderated")),
        "color_scheme": a.get("color_scheme", md.get("color_scheme")),
        "theme_id": a.get("theme_id", md.get("theme_id")),
        "font_id": a.get("font_id", md.get("font_id")),
        "upload_limit": a.get("upload_limit", md.get("upload_limit")),
        "video_length_limit": a.get("video_length_limit", md.get("video_length_limit")),
        "audio_length_limit": a.get("audio_length_limit", md.get("audio_length_limit")),
        "show_author": a.get("show_author", md.get("show_author")),
        "filter_profanity": a.get("filter_profanity", md.get("filter_profanity")),
        "is_premium": a.get("is_premium", md.get("is_premium")),
        "archived_at": a.get("archived_at", md.get("archived_at")),
        "builder_id": b.get("id"),
        "builder_username": b.get("username"),
        "builder_paying": b.get("paying"),
        "source": "api",                            # どこから取ったか（API失敗時は md）
    }
    return meta, hashid


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

    # 3. ボード情報の取得（API優先／失敗時のみmdへフォールバック）
    meta, hashid = build_meta(board_id, md_path)

    # 4. 統計値の取得とCSV保存（is_info に関係なく必ず実行）
    ana = fetch_analytics(board_id, ana_cache)

    if ana.get("pageviews") is not None:
        csv_path = os.path.join(CSV_DIR, name,
                                now_jst_dt.strftime("%Y"),
                                now_jst_dt.strftime("%m") + ".csv")
        ts_str = now_jst_dt.strftime("%Y-%m-%d %H:%M:%S")
        n = update_csv(csv_path, ts_str, {
            # 統計値
            "pageviews": ana.get("pageviews"),
            "visitors": ana.get("visitors"),
            "engagementTimeMin": ana.get("engagementTimeMin"),
            # ボード属性（API由来）
            "posts": meta.get("posts") or "",
            "viz": meta.get("viz", ""),
            "is_commentable": meta.get("is_commentable", ""),
            "is_reactable": meta.get("is_reactable", ""),
            "is_remakeable": meta.get("is_remakeable", ""),
            "is_premium": meta.get("is_premium", ""),
            "created": meta.get("created", ""),
            "updated": meta.get("updated", ""),
            "builder": meta.get("builder", ""),
            "title": meta.get("title", ""),
            "source": meta.get("source", "md"),
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

    if os.path.exists(md_path) or meta.get("source") == "api":
        info_data[key] = dict(meta)
        info_data[key].update({
            "board_id": board_id,
            "hashid": ana.get("hashid") or meta.get("hashid"),
            "pageviews": ana.get("pageviews"),
            "visitors": ana.get("visitors"),
            "engagementTimeMin": ana.get("engagementTimeMin"),
        })
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
