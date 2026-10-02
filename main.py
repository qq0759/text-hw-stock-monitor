import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import random
import requests
import csv
import os
import json
import winsound
from datetime import datetime
import webbrowser

WATCH_INTERVAL = 30
TIMEOUT = 10
LOG_FILE = "price_log.csv"
CONFIG_FILE = "config.json"

HAVE_KW = ["加入购物车", "立即购买", "立即抢购", "现在购买", "add to cart"]
NO_KW = ["到货通知", "库存不足", "暂时缺货", "暂无现货", "已售罄", "out of stock"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

def log_write(product_name, status, detail=""):
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["时间", "商品名", "状态", "详情"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                         product_name, status, detail])

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"wecom_webhook": "", "autostart": False,
            "sound": True, "wecom_push": False, "items": []}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

class Watcher(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app

    def run(self):
        while self.app.running:
            for item in list(self.app.watch_list):
                if not self.app.running:
                    break
                try:
                    status = self.check_stock(item["url"])
                    self.app.root.after(0, self.app.update_status, item, status)
                except Exception as e:
                    self.app.root.after(0, self.app.log, f"❌ {item['name']} 检查失败: {e}")
            time.sleep(WATCH_INTERVAL + random.uniform(0, 10))

    def check_stock(self, url):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            t = r.text
            if any(k in t for k in HAVE_KW):
                return "AVAILABLE"
            if any(k in t for k in NO_KW):
                return "SOLD_OUT"
            return "UNKNOWN"
        except Exception as e:
            err = str(e)
            if "403" in err or "429" in err:
                return "BLOCKED"
            return "ERROR"

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("华为商城库存监控")
        self.root.geometry("820x620")
        self.root.resizable(True, True)

        self.watch_list = []
        self.running = False
        self.watcher = None
        self.config = load_config()

        self.build_ui()
        self.load_saved_items()

    def build_ui(self):
        frm_top = ttk.Frame(self.root, padding=10)
        frm_top.pack(fill="x")

        ttk.Label(frm_top, text="商品链接：").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar()
        self.entry_url = ttk.Entry(frm_top, textvariable=self.url_var, width=60)
        self.entry_url.grid(row=0, column=1, padx=5)
        ttk.Button(frm_top, text="添加监控", command=self.add_item).grid(row=0, column=2, padx=5)

        ttk.Label(frm_top, text="备注名：").grid(row=1, column=0, sticky="w", pady=5)
        self.name_var = tk.StringVar()
        ttk.Entry(frm_top, textvariable=self.name_var, width=30).grid(
            row=1, column=1, sticky="w", padx=5)

        frm_ctrl = ttk.Frame(self.root, padding=5)
        frm_ctrl.pack(fill="x", padx=10)
        self.btn_start = ttk.Button(frm_ctrl, text="▶ 开始监控", command=self.start)
        self.btn_start.pack(side="left", padx=5)
        self.btn_stop = ttk.Button(frm_ctrl, text="⏹ 停止",
                                   command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=5)
        ttk.Button(frm_ctrl, text="🗑 删除选中", command=self.del_item).pack(side="left", padx=5)
        ttk.Button(frm_ctrl, text="🌐 打开商品页", command=self.open_url).pack(side="left", padx=5)
        ttk.Button(frm_ctrl, text="📊 查看历史", command=self.show_history).pack(side="left", padx=5)
        ttk.Button(frm_ctrl, text="📋 导出日志", command=self.export_log).pack(side="left", padx=5)

        frm_set = ttk.LabelFrame(self.root, text="设置", padding=5)
        frm_set.pack(fill="x", padx=10, pady=5)
        self.sound_var = tk.BooleanVar(value=self.config.get("sound", True))
        ttk.Checkbutton(frm_set, text="🔊 有货提示音", variable=self.sound_var).pack(side="left", padx=5)
        self.wecom_var = tk.BooleanVar(value=self.config.get("wecom_push", False))
        ttk.Checkbutton(frm_set, text="企微推送", variable=self.wecom_var).pack(side="left", padx=5)
        ttk.Label(frm_set, text="Webhook:").pack(side="left", padx=(15, 2))
        self.webhook_var = tk.StringVar(value=self.config.get("wecom_webhook", ""))
        ttk.Entry(frm_set, textvariable=self.webhook_var, width=35).pack(side="left", padx=2)

        frm_list = ttk.LabelFrame(self.root, text="监控列表", padding=5)
        frm_list.pack(fill="both", expand=True, padx=10, pady=5)

        columns = ("name", "url", "status", "price", "note")
        self.tree = ttk.Treeview(frm_list, columns=columns, show="headings", height=8)
        self.tree.heading("name", text="商品名")
        self.tree.heading("url", text="链接")
        self.tree.heading("status", text="状态")
        self.tree.heading("price", text="最新价")
        self.tree.heading("note", text="备注")
        self.tree.column("name", width=130)
        self.tree.column("url", width=330)
        self.tree.column("status", width=90)
        self.tree.column("price", width=70)
        self.tree.column("note", width=100)
        self.tree.pack(fill="both", expand=True)

        self.tree.tag_configure("avail", foreground="green")
        self.tree.tag_configure("soldout", foreground="gray")
        self.tree.tag_configure("blocked", foreground="orange")
        self.tree.tag_configure("unknown", foreground="red")

        frm_log = ttk.LabelFrame(self.root, text="运行日志", padding=5)
        frm_log.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_area = scrolledtext.ScrolledText(frm_log, height=7, wrap="word")
        self.log_area.pack(fill="both", expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def add_item(self):
        url = self.url_var.get().strip()
        name = self.name_var.get().strip() or "未命名商品"
        if not url:
            messagebox.showwarning("提示", "请粘贴商品链接")
            return
        if not url.startswith("http"):
            messagebox.showwarning("提示", "链接格式不对")
            return
        item = {"name": name, "url": url, "status": "等待中", "price": "-", "note": ""}
        self.watch_list.append(item)
        self.tree.insert("", "end", iid=str(len(self.watch_list)-1), values=(
            item["name"], item["url"], item["status"], item["price"], item["note"]))
        self.url_var.set("")
        self.name_var.set("")
        self.log(f"➕ 已添加: {name}")

    def del_item(self):
        sel = self.tree.selection()
        if not sel:
            return
        for s in sel:
            idx = int(s)
            if 0 <= idx < len(self.watch_list):
                name = self.watch_list[idx]["name"]
                self.watch_list.pop(idx)
                self.log(f"🗑 已删除: {name}")
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(self.watch_list):
            self.tree.insert("", "end", iid=str(i), values=(
                it["name"], it["url"], it.get("status","等待中"),
                it.get("price","-"), it.get("note","")))

    def start(self):
        if not self.watch_list:
            messagebox.showinfo("提示", "先添加至少一个商品链接")
            return
        self.running = True
        self.watcher = Watcher(self)
        self.watcher.start()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.log("▶ 监控已启动")

    def stop(self):
        self.running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.log("⏹ 监控已停止")

    def update_status(self, item, status):
        if item not in self.watch_list:
            return
        idx = self.watch_list.index(item)
        old = item["status"]
        item["status"] = status

        tag = ""
        if status == "AVAILABLE":
            tag = "avail"
            if old != "AVAILABLE":
                self.notify_available(item)
        elif status == "SOLD_OUT":
            tag = "soldout"
        elif status == "BLOCKED":
            tag = "blocked"
        elif status == "UNKNOWN":
            tag = "unknown"

        self.tree.item(str(idx), values=(
            item["name"], item["url"], status, item["price"], item["note"]),
            tags=(tag,))

        if status == "AVAILABLE":
            log_write(item["name"], "有货", item["url"])
        elif status == "BLOCKED":
            log_write(item["name"], "风控拦截", "")

        self.log(f"{item['name']} => {status}")

    def notify_available(self, item):
        msg = f"{item['name']} 有货了！\n{item['url']}"
        self.log(f"🔔🔔🔔 {msg}")
        try:
            messagebox.showinfo("🎉 有货提醒", msg)
        except Exception:
            pass
        if self.sound_var.get():
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
        if self.wecom_var.get() and self.webhook_var.get():
            try:
                requests.post(self.webhook_var.get(), json={
                    "msgtype": "text",
                    "text": {"content": f"🎉 华为商城到货提醒\n{item['name']}\n{item['url']}"}
                }, timeout=5)
            except Exception:
                pass

    def open_url(self):
        sel = self.tree.selection()
        if sel:
            idx = int(sel[0])
            if 0 <= idx < len(self.watch_list):
                webbrowser.open(self.watch_list[idx]["url"])

    def show_history(self):
        win = tk.Toplevel(self.root)
        win.title("历史记录")
        win.geometry("700x400")
        txt = scrolledtext.ScrolledText(win, wrap="word")
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8-sig") as f:
                txt.insert("1.0", f.read())
        else:
            txt.insert("1.0", "暂无历史记录")

    def export_log(self):
        if os.path.exists(LOG_FILE):
            os.startfile(LOG_FILE)
        else:
            messagebox.showinfo("提示", "还没有日志文件")

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_area.insert("end", f"[{ts}] {msg}\n")
        self.log_area.see("end")

    def load_saved_items(self):
        if "items" in self.config:
            for it in self.config["items"]:
                self.watch_list.append(it)
                idx = len(self.watch_list) - 1
                self.tree.insert("", "end", iid=str(idx), values=(
                    it["name"], it["url"], it.get("status","等待中"),
                    it.get("price","-"), it.get("note","")))

    def on_close(self):
        self.running = False
        self.config["wecom_webhook"] = self.webhook_var.get()
        self.config["sound"] = self.sound_var.get()
        self.config["wecom_push"] = self.wecom_var.get()
        self.config["items"] = self.watch_list
        save_config(self.config)
        self.root.destroy()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = App()
    app.run()
