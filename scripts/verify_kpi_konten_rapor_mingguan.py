#!/usr/bin/env python3
"""INV-F40 (sesi #35) — **KPI KONTEN PER KONTEN** & **RAPOR KREATOR MINGGUAN**.

Yang diukur SEBELUM sesi ini (bukan dugaan):
  * `POST /content-calendar/{id}/kpi` sudah ada sejak F7.3 tetapi **0 layar**
    memanggilnya ⇒ seluruh angka views/engagement/GMV konten hanya bisa lahir
    dari penyemai demo. Pemilik minta KPI per konten; jalan masuknya belum ada.
  * `/performance` hanya bisa dikelompokkan `creator|content_type|account` ⇒ tidak
    ada satu pun cara membaca KPI **satu konten** (satuan kerja yang dinilai).
  * Insentif dibaca per periode 3 bulan, performa per bulan ⇒ tidak ada rapor
    mingguan; kreator baru tahu tertinggal saat periode hampir habis.

Yang dijaga gate ini:
 A. **KPI per konten** — satu baris = satu konten; baris tanpa KPI TIDAK
    disembunyikan; angka turunan DIHITUNG server (bukan ketikan); KPI tanpa link
    terbit ditolak 400; rekap kelompok dan daftar per-konten memakai angka yang
    SAMA; `group_by=platform` dilayani.
 B. **Rapor kreator mingguan** — pekan = 7 hari BERGULIR; nominal insentif
    DIBACA dari layar insentif (tidak dihitung ulang); GMV platform & omzet
    pesanan tetap DUA kolom; pengiriman idempoten per (kreator, pekan); SMTP
    belum diisi tidak pernah gagal senyap; kreator membaca rapornya sendiri
    TANPA HPP/margin; kreator tanpa konten tetap dilaporkan.

Skrip ini MEMBERSIHKAN artefaknya sendiri (konten uji + dokumen pengiriman uji).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

API = os.environ.get("API_BASE", "http://localhost:8001")
G, R, Y, C, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[1m", "\033[0m"
PASS: list[str] = []
FAIL: list[str] = []
STAMP = time.strftime("%H%M%S")
TAG = f"GATE40 {STAMP}"


def ok(code, msg, detail=""):
    PASS.append(code)
    print(f"  {G}✓ {code}{X} {msg}" + (f"\n         {C}{detail}{X}" if detail else ""))


def bad(code, msg, detail=""):
    FAIL.append(code)
    print(f"  {R}✗ {code} {msg}{X}" + (f"\n         {detail}" if detail else ""))


def head(t):
    print(f"\n{C}{B}▶ {t}{X}")


def det(d):
    return json.dumps(d, ensure_ascii=False, default=str)[:260]


def call(method, path, token=None, body=None):
    req = urllib.request.Request(
        f"{API}{path}", data=json.dumps(body).encode() if body is not None else None,
        method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except ValueError:
            return e.code, {"raw": raw[:300].decode(errors="ignore")}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def main() -> int:  # noqa: C901
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env")
    from pymongo import MongoClient
    db = MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "test_database")]

    st, d = call("POST", "/api/auth/login", None,
                 {"email": os.environ.get("ADMIN_EMAIL", "admin@garment.com"),
                  "password": os.environ.get("ADMIN_PASS", "Admin@123")})
    token = (d or {}).get("token")
    if not token:
        bad("SETUP", f"login admin gagal (HTTP {st})", det(d))
        return 1

    st, cl = call("GET", "/api/marketing/kol/creators?limit=1", token)
    creators = (cl or {}).get("creators") or []
    if not creators:
        bad("SETUP", "tidak ada kreator untuk diuji", det(cl))
        return 1
    creator = creators[0]
    cid = creator["id"]

    today = date.today()
    d_in = (today - timedelta(days=2)).isoformat()      # di dalam pekan bergulir
    d_out = (today - timedelta(days=40)).isoformat()    # di luar pekan bergulir
    made: list[str] = []

    def make_content(day: str, *, url: str = "", status: str = "draft", title: str = "") -> str:
        st, r = call("POST", "/api/marketing/content-calendar", token, {
            "account_id": creator.get("assigned_account_ids", [None])[0] or "",
            "account_name": "GATE40", "platform": "tiktok", "date": day,
            "content_type": "reels_tiktok", "title": title or f"{TAG} {day}",
            "status": status, "published_url": url, "creator_id": cid,
            "description": TAG,
        })
        if st != 200:
            bad("SETUP", f"gagal membuat konten uji (HTTP {st})", det(r))
            return ""
        made.append(r["data"]["id"])
        return r["data"]["id"]

    try:
        # ══ A. KPI PER KONTEN ═════════════════════════════════════════════════
        head("A — KPI PER KONTEN: satuan terkecil, baris kosong terlihat, turunan dihitung")

        c_no_url = make_content(d_in)                                     # tanpa link
        c_kpi = make_content(d_in, url="https://demo.tiktok.com/gate40", status="posted")
        make_content(d_out, url="https://demo.tiktok.com/gate40-lama", status="posted")

        st, r = call("POST", f"/api/marketing/content-calendar/{c_no_url}/kpi", token,
                     {"views": 1000, "likes": 10})
        if st == 400:
            ok("A1", "KPI konten TANPA link terbit ditolak 400 — angka yang tidak bisa "
                     "dicek ulang tidak masuk laporan")
        else:
            bad("A1", f"KPI tanpa link terbit DITERIMA (HTTP {st})", det(r))

        kpi_in = {"views": 4000, "likes": 300, "comments": 40, "shares": 20, "saves": 60,
                  "ctr": 2.5, "orders": 12, "gmv": 3_600_000,
                  "published_url": "https://demo.tiktok.com/gate40", "source": "manual"}
        st, r = call("POST", f"/api/marketing/content-calendar/{c_kpi}/kpi", token, kpi_in)
        drv = ((r or {}).get("data") or {}).get("kpi_derived") or {}
        exp_eng = 300 + 40 + 20
        if st != 200:
            bad("A2", f"pengisian KPI manual gagal (HTTP {st})", det(r))
        elif (drv.get("engagement") != exp_eng
              or round(drv.get("engagement_rate", 0), 2) != round(exp_eng / 4000 * 100, 2)
              or round(drv.get("cvr", 0), 4) != round(12 / 4000 * 100, 4)
              or round(drv.get("aov", 0)) != round(3_600_000 / 12)):
            bad("A2", "angka turunan KPI TIDAK sama dengan hitungan seharusnya "
                      "(engagement/eng.rate/CVR/AOV)", det(drv))
        else:
            ok("A2", f"turunan KPI dihitung server: engagement {exp_eng} · "
                     f"eng.rate {drv['engagement_rate']}% · CVR {drv['cvr']}% · AOV {drv['aov']:.0f}")
        if ((r or {}).get("data") or {}).get("status") == "posted":
            ok("A3", "konten yang KPI-nya terisi otomatis berstatus 'posted' — tidak ada "
                     "baris 'draft' berangka nyata")
        else:
            bad("A3", "konten ber-KPI masih berstatus bukan 'posted'", det(r))

        qs = f"date_from={d_in}&date_to={d_in}"
        st, allr = call("GET", f"/api/marketing/content-calendar/performance/contents?{qs}", token)
        st2, miss = call("GET", f"/api/marketing/content-calendar/performance/contents?{qs}"
                               "&kpi_state=missing", token)
        st3, fill = call("GET", f"/api/marketing/content-calendar/performance/contents?{qs}"
                               "&kpi_state=filled", token)
        if 200 not in (st, st2, st3) or st != 200 or st2 != 200 or st3 != 200:
            bad("A4", f"daftar per-konten gagal (HTTP {st}/{st2}/{st3})", det(allr))
        else:
            n_all = allr["totals"]["contents"]
            if n_all != len(allr["rows"]):
                bad("A4", f"satu baris ≠ satu konten (rows {len(allr['rows'])} vs "
                          f"totals {n_all})")
            elif n_all != miss["totals"]["contents"] + fill["totals"]["contents"]:
                bad("A4", "baris tanpa KPI tersembunyi: semua ≠ (belum + sudah)",
                    f"{n_all} vs {miss['totals']['contents']}+{fill['totals']['contents']}")
            else:
                ok("A4", f"{n_all} konten = {miss['totals']['contents']} belum ber-KPI + "
                         f"{fill['totals']['contents']} sudah — tidak ada baris disembunyikan")
            mine = [r for r in allr["rows"] if r["id"] in (c_kpi, c_no_url)]
            if len(mine) == 2 and all("kpi_derived" in r and "kpi_filled" in r for r in mine):
                ok("A5", "setiap baris membawa kreator, jenis, toko, status KPI, dan "
                         "angka turunannya")
            else:
                bad("A5", "baris per-konten tidak lengkap (kreator/jenis/turunan/status KPI)",
                    det(mine))

        st, grp = call("GET", "/api/marketing/content-calendar/performance"
                             f"?group_by=content_type&date_from={d_in}&date_to={d_in}", token)
        if st != 200:
            bad("A6", f"rekap per jenis gagal (HTTP {st})", det(grp))
        elif round(grp["totals"]["views"], 2) != round(allr["totals"]["views"], 2):
            bad("A6", "rekap kelompok dan daftar per-konten memberi total views BERBEDA",
                f"{grp['totals']['views']} vs {allr['totals']['views']}")
        else:
            ok("A6", f"rekap per jenis & daftar per-konten sepakat: "
                     f"{grp['totals']['views']:.0f} views")

        for gb in ("account", "platform", "creator"):
            st, g = call("GET", "/api/marketing/content-calendar/performance"
                               f"?group_by={gb}&date_from={d_in}&date_to={d_in}", token)
            if st != 200 or g.get("group_by") != gb:
                bad("A7", f"pengelompokan '{gb}' tidak dilayani (HTTP {st})", det(g))
                break
        else:
            ok("A7", "KPI konten bisa dibaca per konten · per jenis · per toko · "
                     "per platform · per KOL")

        # ══ B. RAPOR KREATOR MINGGUAN ═════════════════════════════════════════
        head("B — RAPOR MINGGUAN: 7 hari bergulir, satu sumber insentif, kirim idempoten")
        st, rep = call("GET", f"/api/marketing/kol/weekly-report?creator_id={cid}", token)
        if st != 200 or not rep.get("rows"):
            bad("B1", f"rapor mingguan gagal (HTTP {st})", det(rep))
            row = {}
        else:
            p = rep["period"]
            span = (date.fromisoformat(p["end"]) - date.fromisoformat(p["start"])).days
            if span != 6:
                bad("B1", f"pekan bukan 7 hari bergulir (selisih {span} hari)", det(p))
            else:
                ok("B1", f"pekan = 7 hari bergulir {p['start']} … {p['end']}")
            row = rep["rows"][0]

        if row:
            st, inc = call("GET", f"/api/marketing/kol/creators/{cid}/incentive", token)
            if st != 200:
                bad("B2", f"ringkasan insentif tidak terbaca (HTTP {st})", det(inc))
            elif (round(row["incentive_total"], 2) != round(inc["total_incentive"], 2)
                  or row["pcs_period"] != inc["pcs_sold"]
                  or row["incentive_period"]["start"] != inc["period"]["start"]):
                bad("B2", "rapor mingguan MENGHITUNG ULANG insentif — nominalnya berbeda "
                          "dari layar insentif",
                    f"rapor {row['incentive_total']}/{row['pcs_period']} vs "
                    f"insentif {inc['total_incentive']}/{inc['pcs_sold']}")
            else:
                ok("B2", f"nominal insentif dibaca dari SATU sumber "
                         f"(Rp {row['incentive_total']:.0f} · {row['pcs_period']} pcs · "
                         f"periode {row['incentive_period']['start']})")

            if "gmv_kpi" in row and "order_revenue" in row and "revenue_total" not in row:
                ok("B3", "GMV platform & omzet pesanan tetap DUA kolom — tidak pernah "
                         "dijumlah menjadi satu angka")
            else:
                bad("B3", "ada kolom omzet gabungan di rapor (risiko hitung ganda)",
                    det(list(row.keys())))

            # konten pekan ini vs daftar per-konten dengan jendela & kreator yang sama
            p = rep["period"]
            st, mine = call("GET", "/api/marketing/content-calendar/performance/contents"
                                   f"?creator_id={cid}&date_from={p['start']}&date_to={p['end']}",
                            token)
            if st == 200 and mine["totals"]["contents"] == row["contents"] \
                    and round(mine["totals"]["views"], 2) == round(row["views"], 2):
                ok("B4", f"jumlah konten & views rapor = daftar per-konten pada jendela "
                         f"yang sama ({row['contents']} konten · {row['views']:.0f} views)")
            else:
                bad("B4", "rapor mingguan dan daftar per-konten tidak sepakat",
                    f"rapor {row['contents']}/{row['views']} vs "
                    f"{mine.get('totals')}")

            if row["contents"] and row["with_kpi"] < row["contents"]:
                if any("Cakupan KPI" in n for n in rep["data_notes"]):
                    ok("B8", "rapor menyebut cakupan KPI saat masih ada konten tanpa angka")
                else:
                    bad("B8", "konten tanpa KPI TIDAK diberitahukan di rapor")
            else:
                ok("B8", "seluruh konten pekan ini sudah ber-KPI (tidak ada yang perlu "
                         "diperingatkan)")

        st, snd = call("POST", "/api/marketing/kol/weekly-report/send", token,
                       {"creator_ids": [cid]})
        st2, snd2 = call("POST", "/api/marketing/kol/weekly-report/send", token,
                         {"creator_ids": [cid]})
        runs = db.marketing_creator_weekly_reports.count_documents(
            {"creator_id": cid, "week_end": (snd.get("period") or {}).get("end")})
        if st != 200 or st2 != 200:
            bad("B5", f"pengiriman rapor gagal (HTTP {st}/{st2})", det(snd))
        elif runs != 1:
            bad("B5", f"dua kali kirim meninggalkan {runs} dokumen untuk pekan yang sama "
                      "(tidak idempoten)")
        else:
            ok("B5", "dua kali kirim tetap SATU dokumen per (kreator, pekan)")

        res = (snd.get("results") or [{}])[0]
        if not snd.get("smtp_configured"):
            if res.get("status") == "skipped_no_smtp" and "SMTP" in (res.get("error") or ""):
                ok("B6", "SMTP belum diisi → status 'skipped_no_smtp' + alasannya disebut "
                         "(rapor tetap tersimpan, tidak gagal senyap)")
            else:
                bad("B6", "SMTP belum diisi tetapi statusnya tidak jujur", det(res))
        elif res.get("status") in ("sent", "failed"):
            ok("B6", f"SMTP aktif → status pengiriman nyata dilaporkan: {res.get('status')}")
        else:
            bad("B6", "status pengiriman tidak dikenali", det(res))

        # kreator membaca rapornya sendiri — TANPA HPP/margin
        email = creator.get("login_email") or ""
        if not email:
            bad("B7", "kreator uji tidak punya akun portal — tidak bisa memeriksa "
                      "kebocoran HPP")
        else:
            st, lg = call("POST", "/api/marketing/creator-portal/auth/login", None,
                          {"email": email, "password": os.environ.get("CREATOR_PASS", "Dewi@123")})
            ctok = (lg or {}).get("access_token") or (lg or {}).get("token")
            if not ctok:
                bad("B7", f"login portal kreator gagal (HTTP {st})", det(lg))
            else:
                st, mine = call("GET", "/api/marketing/creator-portal/my-weekly-report", ctok)
                blob = json.dumps(mine, ensure_ascii=False).lower()
                leaks = [k for k in ("hpp", "margin", "login_email", "password") if k in blob]
                if st != 200:
                    bad("B7", f"kreator tidak bisa membaca rapornya (HTTP {st})", det(mine))
                elif leaks:
                    bad("B7", f"rapor kreator membocorkan field terlarang: {leaks}")
                else:
                    ok("B7", "kreator membaca rapor mingguannya sendiri; tidak ada "
                             "HPP/margin/kredensial di dalamnya")

        st, allrep = call("GET", "/api/marketing/kol/weekly-report", token)
        idle = [r for r in (allrep.get("rows") or []) if r["contents"] == 0]
        if st != 200:
            bad("B9", f"rapor semua kreator gagal (HTTP {st})", det(allrep))
        elif idle and not any("TIDAK punya satu konten" in n for n in allrep["data_notes"]):
            bad("B9", f"{len(idle)} kreator tanpa konten tidak disebut di catatan rapor")
        else:
            ok("B9", f"kreator tanpa konten tetap dilaporkan ({len(idle)} kreator) — "
                     "bukan disembunyikan dari rapat")

    finally:
        # ══ BERSIH-BERSIH: artefak uji tidak boleh tertinggal ═════════════════
        for entry_id in made:
            call("DELETE", f"/api/marketing/content-calendar/{entry_id}", token)
        left = db.marketing_content_calendar.count_documents({"description": TAG})
        db.marketing_content_calendar.delete_many({"description": TAG})
        db.marketing_creator_weekly_reports.delete_many({"creator_id": cid})
        if left == 0:
            ok("Z1", f"{len(made)} konten uji dihapus lewat endpoint resmi; "
                     "dokumen pengiriman uji dibersihkan")
        else:
            bad("Z1", f"{left} konten uji tertinggal setelah dihapus lewat endpoint")

    print(f"\n{B}{'─' * 70}{X}")
    if FAIL:
        print(f"{R}{B}VERDICT MERAH — {len(FAIL)} invarian gagal: {', '.join(FAIL)}{X}")
        return 1
    print(f"{G}{B}VERDICT HIJAU — {len(PASS)} invarian sesi #35 terjaga{X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
