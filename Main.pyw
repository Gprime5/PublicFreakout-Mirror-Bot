from tkinter import Tk, Frame, Menu
from tkinter.ttk import Treeview, Scrollbar, Style, Entry, Label, Button
from PublicFreakout import PF
import threading
import webbrowser as w

class main(Tk):
    def __init__(self):
        Tk.__init__(self)

        self.title("Public Freakout But")
        self.minsize(600, 300)

        self.control_btn = Button(self, text="Start", command=self.control)
        self.control_btn.grid(padx=5, pady=5, sticky="w")

        lbl = Label(self, text="Skip to Nth newest post:")
        lbl.grid(column=1, row=0)

        self.entry = Entry(self)
        self.entry.grid(column=2, row=0, padx=5, pady=5, sticky="w")

        self.lbl = Label(self)
        self.lbl.grid(column=0, row=1, padx=5, pady=5, sticky="w")

        self.tv = self.tree(0, 2, columnspan=3)

        self.item = Label(self, wraplength=500)
        self.item.grid(column=0, row=3, columnspan=2, padx=5, pady=5, sticky="sw")

        self.r_menu = Menu(self, tearoff=0)
        self.r_menu.add_command(label="Open", command=self.r_open)

        self.s_menu = Menu(self, tearoff=0)
        self.s_menu.add_command(label="Open", command=self.s_open)

        self.PF = PF(self.log)

        self.protocol("WM_DELETE_WINDOW", self.end_all)
        self.mainloop()

    def end_all(self):
        self.PF.stop()

        if len(threading.enumerate()) > 1:
            self.after(1000, self.end_all)
        else:
            self.destroy()

    def control(self):
        if self.control_btn["text"] == "Start":
            threading.Thread(target=self.run).start()
            self.control_btn["text"] = "Stop"
        else:
            self.PF.stop()
            self.control_btn["text"] = "Start"

    def r_open(self):
        item = self.tv.selection()
        w.open("https://redd.it/" + item[0])

    def s_open(self):
        item = self.tv.selection()
        w.open("https://streamable.com/" + self.tv.item(item, "values")[2])

    def log(self, txt):
        self.lbl["text"] = txt

    def select(self, args):
        item = self.tv.identify_row(args.y)
        self.item["text"] = self.tv.item(item, "text")

    def tree(self, c=0, r=0, **kwargs):
        self.columnconfigure(c, weight=1)
        self.rowconfigure(r, weight=1)

        tree_frame = Frame(self)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.grid(column=c, row=r, sticky="nwse", padx=5, pady=5, **kwargs)

        def scroll(sbar, first, last):
            """Hide and show scrollbar as needed."""
            first, last = float(first), float(last)
            if first <= 0 and last >= 1:
                sbar.grid_remove()
            else:
                sbar.grid()
            sbar.set(first, last)

        x = lambda f, l: scroll(xs, f, l)
        y = lambda f, l: scroll(ys, f, l)
        tv = Treeview(tree_frame, xscroll=x, yscroll=y)
        tv.grid(sticky="nwes")

        xs = Scrollbar(tree_frame, orient='horizontal', command=tv.xview)
        xs.grid(column=0, row=1, sticky="ew")

        ys = Scrollbar(tree_frame, orient='vertical', command=tv.yview)
        ys.grid(column=1, row=0, sticky="ns")

        Style().layout("Treeview", [('Treeview.treearea', {'sticky': 'nswe'})])

        tv.heading("#0", text="Reddit", anchor='w')
        tv.column("#0", stretch=0, anchor="w", minwidth=200, width=200)

        tv["columns"] = ["Status", "time", "Streamable"]
        for i, w in zip(tv["columns"][:-1], (180, 140, 30)):
            tv.heading(i, text=i, anchor='w')
            tv.column(i, stretch=0, anchor='w', minwidth=w, width=w)

        i = tv["columns"][-1]
        tv.heading(i, text=i, anchor='w')
        tv.column(i, stretch=1, anchor='w', minwidth=70, width=70)

        tv.bind("<Button-1>", self.select)
        tv.bind("<Button-3>", self.popup)

        return tv
    
    def popup(self, args):
        item = self.tv.identify_row(args.y)
        row = self.tv.identify_column(args.x)

        self.tv.selection_set(item)
        if item:
            if row == "#0":
                self.r_menu.post(args.x_root, args.y_root)
            elif row == "#3":
                if len(self.tv.item(item, "values")) == 3:
                    self.s_menu.post(args.x_root, args.y_root)

    def run(self):
        while self.PF.on:
            self.PF.start(int(self.entry.get() or 0))
            self.entry.delete(0, "end")

            for i in self.PF.run():
                self.process(i)

    def process(self, i):
        self.tv.insert("", 0, i.id, text=i.title, values=("Starting",))
        status, time, code = self.PF.process(i)
        self.tv.item(i.id, values=(status, time))

        if status == "Reddit submission":
            self.tv.item(i.id, values=("Downloading video", time))
            self.PF.download("video", i.media["reddit_video"]["fallback_url"])
            if i.media["Uploading gif"]:
                self.item(i.id, values=("Uploading gif", time))
                status, time, code = ("Uploading gif", time, self.PF.upload("video", i.title))
            else:
                self.tv.item(i.id, values=("Downloading audio", time))
                self.PF.download("audio", i.media["reddit_video"]["fallback_url"].rsplit("/", 1)[0] + "/audio")
                self.tv.item(i.id, values=("Combining media", time))
                self.PF.combine_media()
                self.tv.item(i.id, values=("Uploading video"))
                status, time, code = ("Uploading video", time, self.PF.upload("output", i.title))
        elif code == "":
            self.save(i.id, (status, time, code))
            return

        for status, time in self.PF.wait_completed(code):
            self.tv.item(i.id, values=(status, time))

        if status == "Videos must be under 10 minutes":
            uploaded = []
            for part, time in self.PF.import_parts(i.url):
                self.tv.item(i.id, values=("Uploading part " + str(part), time))
                status, time, code = ("Uploading part " + str(part), time, self.PF.upload(str(part) + "." + self.PF.ext, "{} [Part {}]".format(i.title, part + 1)))
                uploaded.append(code)

            for u in uploaded:
                for status, time in self.PF.wait_completed(u):
                    self.tv.item(i.id, values=(status, time))

            reddit_post = self.PF.post_to_reddit(i, uploaded)
            self.tv.item(i.id, values=reddit_post)
            self.save(i.id, reddit_post)
            return
        elif "ERROR" in status:
            self.tv.item(i.id, values=(status, time))
            self.save(i.id, code, status, time)
            return

        reddit_post = self.PF.post_to_reddit(i, (code,))
        self.tv.item(i.id, values=reddit_post)
        self.save(i.id, reddit_post)

    def save(self, i, values):
        with open("log.txt", "a") as file:
            if len(values) == 3:
                file.write("https://redd.it/{} | {} | {} | https://streamable.com/{}\n".format(i, *values))
            else:
                file.write("https://redd.it/{} | {} | {} | \n".format(i, *values))

if __name__ == "__main__":
    x = main()
