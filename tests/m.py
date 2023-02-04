#!/usr/bin/python3

import argparse
import base64
import datetime
import filecmp
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import defaultdict


D0 = datetime.datetime(2001, 1, 1).timestamp() - 28800
RX_TEL = re.compile(r"pref:(.+)")
RX_TEL_CANONICAL = re.compile(r"[^\d]")
RX_FNAME = re.compile(r"[^a-z0-9]+")
CCPATH = os.path.expanduser("~/tmp/cc")
HTML_HEAD = """
<html>
<head>
<meta charset="UTF-8">
<style>
body { width: 700; }
.number { font-size: 13pt; color: darkgray; }
.dt { font-size: 10pt; color: darkgray; margin: 0px; }
.day { font-size: 11pt; color: darkgray; margin: 5px; text-align: center; }
.other { font-size: 11pt; color: black; margin: 0px; text-align: left; }
.mine { font-size: 11pt; color: darkblue; margin: 0px; text-align: right; }
</style>
</head>
<body>
"""


class Html:
    def __init__(self, title=None):
        self.title = title
        self.messages = []

    def add_msg(self, msg):
        if isinstance(msg, list):
            self.messages.extend(msg)

        else:
            self.messages.append(msg)

    def rendered(self, all_chats=None):
        res = []
        res.append("%s\n" % HTML_HEAD.strip())
        if self.title:
            res.append("<h1>%s</h1>\n" % self.title)

        ld = None
        for msg in self.messages:
            if ld != msg.day:
                ld = msg.day
                ts = msg.date.strftime("%a %Y-%m-%d")
                res.append('<p class="day">%s</p>\n' % ts)

            res.append(msg.html_representation(all_chats))

        res.append("</body></html>\n")
        return "".join(res)

    def save(self, path, all_chats=None, mode="wt"):
        if mode == "at" and os.path.exists(path):
            print("--> Appending to %s" % path)

        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)

        with open(path, mode) as fh:
            fh.write(self.rendered(all_chats=all_chats))


class Model:
    _tct: str

    @classmethod
    def initialize(cls):
        fields = getattr(cls, "__fields", None)
        if fields is None:
            fields = []
            for line in cls._tct.splitlines():
                for name in line.split(","):
                    if name:
                        name = name.split()[0]
                        fields.append(name)

            setattr(cls, "__fields", fields)

        return fields

    @classmethod
    def get_object(cls, row):
        fields = cls.initialize()
        res = cls()
        for i, n in enumerate(fields):
            if i < len(row):
                value = row[i]
                if "date" in n:
                    value = datetime.datetime.fromtimestamp(value / 1000000000 + D0)

                setattr(res, n, value)

            else:
                pass

        res._on_load()
        return res

    def _on_load(self):
        pass


class Attachment(Model):
    ROWID: int
    mime_type: str
    filename: str
    _tct = """
ROWID, guid, created_date, start_date, filename, uti, mime_type, transfer_state, is_outgoing, user_info, transfer_name, total_bytes,
is_sticker, sticker_user_info, attribution_info, hide_attachment, ck_sync_state, ck_server_change_token_blob, ck_record_id, original_guid,
sr_ck_sync_state, sr_ck_server_change_token_blob, sr_ck_record_id, is_commsafety_sensitive
"""

    def __repr__(self):
        return os.path.basename(getattr(self, "filename", "?"))


class AttachmentJoin(Model):
    message_id: int
    attachment_id: int
    _tct = "message_id, attachment_id"

    def __repr__(self):
        return "attachment %s -> %s" % (self.message_id, self.attachment_id)


class ChatHandles(Model):
    chat_id: int
    handle_id: int
    _tct = "chat_id, handle_id"

    def __repr__(self):
        return "chat %s -> %s" % (self.chat_id, self.handle_id)


class Handle(Model):
    ROWID: int
    id: str
    _tct = "ROWID, id, country, service, uncanonicalized_id, person_centric_id"


class ChatJoin(Model):
    chat_id: int
    message_id: int
    _tct = "chat_id, message_id, message_date"


class Chat(Model):
    ROWID: int
    _tct = """
ROWID, guid, style, state, account_id, properties, chat_identifier, service_name, room_name, account_login, is_archived,
last_addressed_handle, display_name, group_id, is_filtered, successful_query, engram_id, server_change_token, ck_sync_state,
original_group_id, last_read_message_timestamp, sr_server_change_token, sr_ck_sync_state, cloudkit_record_id, sr_cloudkit_record_id,
last_addressed_sim_id, is_blackholed, syndication_date, syndication_type
"""


class Message(Model):
    ROWID: int
    attachments: list = None
    date: datetime.datetime
    text: str
    is_from_me: bool
    _tct = """
ROWID, guid, text, replace, service_center, handle_id, subject, country, attributedBody, version, type, service, account, account_guid,
error, date, date_read, date_delivered, is_delivered, is_finished, is_emote, is_from_me, is_empty, is_delayed, is_auto_reply, is_prepared,
is_read, is_system_message, is_sent, has_dd_results, is_service_message, is_forward, was_downgraded, is_archive, cache_has_attachments,
cache_roomnames, was_data_detected, was_deduplicated, is_audio_message, is_played, date_played, item_type, other_handle, group_title,
group_action_type, share_status, share_direction, is_expirable, expire_state, message_action_type, message_source, associated_message_guid,
associated_message_type, balloon_bundle_id, payload_data, expressive_send_style_id, associated_message_range_location,
associated_message_range_length, time_expressive_send_played, message_summary_info, ck_sync_state, ck_record_id, ck_record_change_tag,
destination_caller_id, sr_ck_sync_state, sr_ck_record_id, sr_ck_record_change_tag, is_corrupt, reply_to_guid, sort_id, is_spam,
has_unseen_mention, thread_originator_guid, thread_originator_part, syndication_ranges, was_delivered_quietly, did_notify_recipient,
synced_syndication_ranges
"""

    def __repr__(self):
        return "%s %s" % (self.date, self.text)

    def _on_load(self):
        self.day = (self.date.year, self.date.month, self.date.day)

    def html_representation(self, all_chats):
        tt = self.date.strftime("%H:%M")
        tt = '<span class="dt">%s</span>' % tt
        if self.is_from_me:
            cl = "mine"
            tt = "%%s %s" % tt

        else:
            cl = "other"
            tt = "%s %%s" % tt

        if all_chats and self.attachments:
            text = []
            for a in self.attachments:
                thumb = b64_thumb(all_chats, a)
                if thumb and not thumb.startswith("["):
                    text.append('<img src="data:image/png;base64,%s">' % thumb)

                else:
                    text.append(thumb or "??")

            text = "<br>\n".join(text)

        else:
            text = self.text

        return '<p class="%s">%s</p>\n' % (cl, tt % text)


def run_program(program, *args):
    p = subprocess.Popen([program] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = p.communicate()
    if p.returncode:
        sys.exit("%s failed: %s\n%s\n%s" % (program, p.returncode, output, error))


def mkdir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def b64_data(all_chats, path):
    if os.path.exists(path):
        tp = os.path.join(all_chats.tmp_path, "%s.png" % os.path.basename(path))
        run_program("/usr/bin/qlmanage", "-t", "-o", all_chats.tmp_path, "-s", "500", path)
        if os.path.exists(tp):
            with open(tp, "rb") as fh:
                data = fh.read()
                data_base64 = base64.b64encode(data)
                data_base64 = data_base64.decode()

            os.unlink(tp)
            return data_base64


def b64_thumb(all_chats, attachment):
    mtype = attachment.mime_type
    if mtype and (mtype.startswith(("image", "video")) or "pdf" in mtype) and attachment.filename:
        ap = attachment.filename.replace("~/Library/Messages", all_chats.mpath)
        data = b64_data(all_chats, ap)
        if data:
            return data

    return "[%s]" % mtype


class SingleChat:

    def __init__(self, chat_info):
        self.chat_info = chat_info
        self.messages = []

    def add_message(self, msg):
        self.messages.append(msg)

    def finalize(self):
        self.messages = sorted(self.messages, key=lambda x: x.date)


class Recipient:

    def __init__(self, phone_id, name=None, category=None):
        self.category = category
        self.phone_id = phone_id
        self.has_name = bool(name)
        self.id = phone_id.strip("+")
        if self.id.startswith("1"):
            self.id = self.id[1:]

        self.name = name or self.id
        self.fname = RX_FNAME.sub(".", self.name.lower())

    def __repr__(self):
        if self.has_name:
            return "%s %s" % (self.name, self.id)

        return self.id

    def __eq__(self, other):
        return isinstance(other, Recipient) and self.phone_id == other.phone_id

    def __hash__(self):
        return hash(self.phone_id)

    @classmethod
    def canonical_nb(cls, text):
        if "@" in text:
            return text

        nb = RX_TEL_CANONICAL.sub("", text)
        if not nb or not (10 <= len(nb) <= 12):
            # print("--> %s" % nb)
            return None

        if not nb.startswith("+"):
            if len(nb) == 10 and nb[0] != 1:
                nb = "1%s" % nb

            nb = "+%s" % nb

        return nb


class AddressBook:

    def __init__(self, path):
        self.path = self.find_ab(path)
        self.phone_map = {}
        if self.path:
            with open(os.path.expanduser(self.path)) as fh:
                for line in fh:
                    t, _, n = line.partition(" ")
                    category, _, n = n.partition(" ")
                    t = t.strip()
                    category = category.strip()
                    assert category in "FGKMUXZ"
                    n = n.strip()
                    if t and n:
                        self.phone_map[t] = Recipient(t, name=n, category=category)

    @staticmethod
    def find_ab(path):
        paths = [os.path.join(path, ".c"), "/tmp/.cc.ksv"]
        for path in paths:
            path = os.path.expanduser(path)
            if os.path.exists(path):
                return path

    def get_name(self, cid):
        r = self.phone_map.get(cid)
        return r.name if r else cid

    def get_recipient(self, cid, canonical=False):
        if canonical:
            cid = Recipient.canonical_nb(cid) or cid

        r = self.phone_map.get(cid)
        return r or Recipient(cid)


class AllChats:

    def __init__(self, mpath):
        self.mpath = os.path.expanduser(mpath)
        self.mhpath = os.path.join(CCPATH, "mh")
        self.pivot_path = os.path.join(CCPATH, ".p")
        self.tmp_path = os.path.join(CCPATH, "_tmp")
        mkdir(self.tmp_path)
        mkdir(self.mhpath)
        self.db = sqlite3.connect(os.path.join(self.mpath, "chat.db"))
        self.chats = {}
        self.address_book = AddressBook(CCPATH)
        self.attachments = {}
        self.attachment_map = defaultdict(list)
        cur = self.db.cursor()
        self.pivot = (0, 0, 0)
        if os.path.exists(self.pivot_path):
            with open(self.pivot_path, "r") as fh:
                pivot = fh.readline()
                if pivot:
                    self.pivot = tuple(int(x) for x in pivot.strip().split(" "))

        for row in cur.execute("SELECT * FROM attachment"):
            c = Attachment.get_object(row)
            self.attachments[c.ROWID] = c

        for row in cur.execute("SELECT * FROM message_attachment_join"):
            c = AttachmentJoin.get_object(row)
            a = self.attachments.get(c.attachment_id)
            if a:
                self.attachment_map[c.message_id].append(a)

            else:
                print("--> missing attachment %s" % c)

        for row in cur.execute("SELECT * FROM chat"):
            c = Chat.get_object(row)
            self.chats[c.ROWID] = SingleChat(c)

        self.chat_map = {}
        for row in cur.execute("SELECT * FROM chat_message_join"):
            c = ChatJoin.get_object(row)
            self.chat_map[c.message_id] = c.chat_id

        self.handles = {}
        for row in cur.execute("SELECT * FROM handle"):
            c = Handle.get_object(row)
            self.handles[c.ROWID] = c

        self.handle_map = defaultdict(list)
        for row in cur.execute("SELECT * FROM chat_handle_join"):
            c = ChatHandles.get_object(row)
            self.handle_map[c.chat_id].append(c.handle_id)

        self.msg_count = 0
        for row in cur.execute("SELECT * FROM message"):
            msg = Message.get_object(row)
            if msg.day >= self.pivot:
                mid = self.chat_map.get(msg.ROWID)
                if mid:
                    self.msg_count += 1
                    msg.attachments = self.attachment_map.get(msg.ROWID)
                    sc = self.chats[mid]
                    sc.add_message(msg)

        print("%s msg" % self.msg_count)
        for sc in self.chats.values():
            sc.finalize()

    def genhtml(self, limit=None):
        actual_chats = [sc for sc in self.chats.values() if sc.messages]
        total = len(actual_chats)
        for i, sc in enumerate(actual_chats):
            if limit and i >= limit:
                return

            print("%s / %s" % (i + 1, total))
            recipients = []
            for hid in self.handle_map[sc.chat_info.ROWID]:
                r = self.address_book.get_recipient(self.handles[hid].id)
                recipients.append(r)

            fname = "%s.html" % "-".join(r.fname for r in recipients)
            cat = sorted(set([r.category for r in recipients if r.category])) or ["_"]
            fname = os.path.join("".join(cat), fname)
            names = ", ".join(r.name for r in recipients)
            numbers = ", ".join(r.phone_id for r in recipients)
            path = os.path.join(self.mhpath, fname)
            title = "<h1>%s" % names
            if any(r.has_name for r in recipients):
                title += ' <span class="number">%s</span>' % numbers

            html = Html(title=title)
            html.add_msg(sc.messages)
            html.save(path, all_chats=self)

    def as_text(self):
        result = []
        for sc in self.chats.values():
            chatters = []
            for hid in self.handle_map[sc.chat_info.ROWID]:
                name = self.address_book.get_name(self.handles[hid].id)
                chatters.append(name)

            chatters = ", ".join(chatters)
            result.append("-------- %s:" % chatters)
            ld = None
            for msg in sc.messages:
                ts = msg.date.strftime("%y%m%d")
                if ld != msg.day:
                    ld = msg.day

                else:
                    ts = "      "

                fr = "+" if msg.is_from_me else " "
                text = msg.text
                if text:
                    text = msg.text.replace("\n", " ").strip()

                result.append("%s %s %s %s" % (ts, msg.date.strftime("%H%M"), fr, text))

            result.append("")

        return "\n".join(result)


class IBChats:
    def __init__(self, path):
        self.path = os.path.expanduser(path)
        self.address_book = AddressBook(CCPATH)
        self.mine = "19253236663"
        self.target_folder = os.path.join(os.path.dirname(path), "sms")
        self.current_msg = None
        self.current_msgs = []
        self.current_senders = []
        self.line_number = 0
        self.empty_lines = 0
        self.prev_line = None

    def canonical_senders(self):
        res = []
        for name in self.current_senders:
            if len(name) <= 6 or "@" in name:
                res.append(Recipient(name))
                continue

            if "(" in name:
                m = re.match(r"^.*?\((.+)\)$", name)
                if m:
                    r = self.address_book.get_recipient(m.group(1))
                    if r:
                        res.append(r)
                        continue

            m = re.match(r"^.*?([\+1]\d+).*?$", name)
            if m:
                r = self.address_book.get_recipient(m.group(1))
                if r:
                    res.append(r)
                    continue

            res.append(Recipient(name))

        return res

    def get_dt(self, line):
        dt = None
        i = None
        if line and len(line) > 30 and line.startswith('"'):
            try:
                i = line.index('",', 1)
                dt = line[1:i]
                dt = datetime.datetime.strptime(dt, "%A, %b %d, %Y  %H:%M")

            except ValueError:
                dt = i = None

        return dt, i

    def wrapup_current_msgs(self):
        self.wrapup_current_msg()
        if self.current_msgs:
            html = Html()
            for msg in self.current_msgs:
                html.add_msg(msg)

            cs = self.canonical_senders()
            if cs:
                dest = "-".join([x.fname for x in cs])
                dest = "%s.html" % dest
                cat = sorted(set([r.category for r in cs if r.category])) or ["_"]
                dest = os.path.join("".join(cat), dest)
                dest = os.path.join(self.target_folder, dest)
                html.save(dest, mode="at")

            else:
                print(html.rendered())

            self.current_msgs = []
            self.current_senders = []

    def wrapup_prev_line(self):
        if self.prev_line is not None:
            if self.current_msg.text:
                self.current_msg.text += "<br>\n"

            self.current_msg.text += self.prev_line
            self.prev_line = None

    def wrapup_current_msg(self):
        self.wrapup_prev_line()
        if self.current_msg and self.current_msg.text is not None:
            if self.current_msg.text.endswith("<br>\n<br>\n"):
                self.current_msg.text = self.current_msg.text[:-10]

            if self.current_msg.text.endswith("<br>\n"):
                self.current_msg.text = self.current_msg.text[:-5]

            self.current_msgs.append(self.current_msg)
            self.current_msg = None

    def process_line(self, line):
        self.wrapup_prev_line()
        if not line:
            self.prev_line = line
            self.empty_lines += 1
            return

        dt, i = self.get_dt(line)
        if dt:
            self.wrapup_current_msg()
            if self.empty_lines == 2:
                self.wrapup_current_msgs()

            line = line[i + 2:]
            sender, _, line = line.partition(",")
            is_from_me = not sender or ("()" in sender) or (self.mine in sender)
            if not is_from_me and sender not in self.current_senders:
                self.current_senders.append(sender)

            _, _, line = line.partition(",")
            imsg, _, line = line.partition(",")
            if imsg and imsg != "Yes":
                print("check imsg line %s: %s" % (self.line_number, imsg))
                sys.exit(1)

            if self.current_msg is None:
                self.current_msg = Message()
                self.current_msg.text = ""

            self.current_msg.date = dt
            self.current_msg.day = (dt.year, dt.month, dt.day)
            self.current_msg.is_from_me = is_from_me
            if line.startswith('"'):
                if len(line) > 1 and line.endswith('"'):
                    line = line[1:-1]

                else:
                    line = line[1:]

        self.empty_lines = 0
        self.prev_line = line

    def process_csv(self):
        self.line_number = 0
        with open(self.path) as fh:
            for line in fh:
                self.line_number += 1
                if self.line_number == 171404:
                    print()
                line = line.rstrip("\n")
                if self.line_number > 1:
                    self.process_line(line)

        self.wrapup_current_msgs()

    def process_txt(self):
        self.line_number = 0
        cday = None
        rd = re.compile(r"^--- (.+) ---$")
        rt = re.compile(r"^\* (.+) +- (.+)$")
        with open(self.path) as fh:
            for line in fh:
                self.line_number += 1
                m = rd.match(line)
                if m:
                    self.wrapup_current_msg()
                    cday = datetime.datetime.strptime(m.group(1), "%b %d, %Y")
                    continue

                m = rt.match(line)
                if m:
                    self.wrapup_current_msg()
                    self.current_msg = Message()
                    self.current_msg.text = None
                    self.current_msg.is_from_me = m.group(1).strip() == "Me"
                    dtt = m.group(2)
                    dt = datetime.datetime.strptime(dtt, "%H:%M:%S %p")
                    hh = dt.hour
                    if hh == 12:
                        if dtt.endswith("AM"):
                            hh = 0

                    elif dtt.endswith("PM"):
                        hh += 12

                    dt = datetime.datetime(cday.year, cday.month, cday.day, hh, dt.minute, dt.second)
                    self.current_msg.date = dt
                    self.current_msg._on_load()
                    continue

                if self.current_msg:
                    if line.startswith(" -") and self.current_msg.text is None:
                        self.current_msg.text = line[2:].strip()
                        continue

                    line = line.rstrip()
                    if self.current_msg.text is not None:
                        if self.current_msg.text:
                            self.current_msg.text += "<br>\n%s" % line

                        else:
                            self.current_msg.text = line

        self.wrapup_current_msgs()


def dcoord(coords, ref):
    dd = coords[0].decimal() + coords[1].decimal() / 60 + coords[2].decimal() / 3600
    if ref.values in "SW":
        dd = -dd

    return dd


class Gpd:
    def __init__(self):
        self.kpath = os.path.join(CCPATH, ".g")
        self.known = []
        with open(self.kpath) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    c1, _, t = line.partition(" ")
                    c1 = float(c1.strip(","))
                    c2, _, t = t.partition(" ")
                    c2 = float(c2)
                    kt = None
                    if t[0] in "th" and t[1] == " ":
                        kt = t[0]
                        t = t[2:]

                    self.known.append((c1, c2, kt, t.strip()))

    def get_loc(self, c1, c2):
        for k1, k2, kt, kn in self.known:
            tol = 0.01
            if kt == "t":
                tol = 0.5

            elif kt == "h":
                tol = 0.005

            if abs(k1 - c1) < tol and abs(k2 - c2) < (tol / 5):
                if kt != "h":
                    return "%s (%s, %s)" % (kn, c1, c2)

                return kn

        return "%s, %s" % (c1, c2)

    def pcoord(self, path):
        import exifread
        res = []
        with open(path, "rb") as fh:
            tt = exifread.process_file(fh, details=False)
            c1 = tt.get("GPS GPSLatitude")
            c2 = tt.get("GPS GPSLongitude")
            if c1 and c2:
                c1 = dcoord(c1.values, tt["GPS GPSLatitudeRef"])
                c2 = dcoord(c2.values, tt["GPS GPSLongitudeRef"])
                res.append(self.get_loc(c1, c2))

            dt = tt.get("EXIF DateTimeOriginal") or tt.get("Image DateTime")
            if dt:
                res.append(dt.values)

        return " ".join(res) or "-"

    def display_coords(self, path):
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            print(self.pcoord(path))
            return

        for fname in os.listdir(path):
            _, _, ext = fname.rpartition(".")
            ext = ext.lower()
            if ext in "heic jpg jpeg mov png":
                fp = os.path.join(path, fname)
                if not os.path.isdir(fp):
                    print("%s: %s" % (fname, self.pcoord(fp)))


def sort_photos(path):
    path = os.path.expanduser(path)
    num = 0
    for fname in os.listdir(path):
        fp = os.path.join(path, fname)
        if os.path.isfile(fp):
            num += 1
            x = os.stat(fp)
            dt = datetime.datetime.fromtimestamp(x.st_mtime)
            folder = os.path.join(path, "%04i/%02i" % (dt.year, dt.month))
            if not os.path.isdir(folder):
                os.makedirs(folder)

            shutil.move(fp, os.path.join(folder, fname))
            if num % 500 == 0:
                print(num)


def check_vcf(path):
    address_book = AddressBook(CCPATH)
    path = os.path.expanduser(path)
    for fname in os.listdir(path):
        if fname.endswith(".vcf"):
            fp = os.path.join(path, fname)
            name = org = None
            phone_ids = []
            with open(fp) as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("ORG:"):
                        org = line[4:]

                    elif line.startswith("FN:"):
                        name = line[3:]

                    elif (line.startswith("TEL;") or line.startswith("EMAIL;")) and ("type=pref:" in line.lower()):
                        i = line.lower().index("type=pref:")
                        tel = Recipient.canonical_nb(line[i + 10:])
                        if tel and tel not in phone_ids:
                            phone_ids.append(tel)

                    elif "tel:" in line.lower():
                        i = line.lower().index("tel:")
                        tel = Recipient.canonical_nb(line[i + 4:])
                        if tel and tel not in phone_ids:
                            phone_ids.append(tel)

            if phone_ids:
                assert name
                if org and org not in name:
                    name = "%s %s" % (name, org)

                for phone_id in phone_ids:
                    if phone_id and phone_id not in address_book.phone_map:
                        if phone_id not in (name, "+%s" % name):
                            print("%s %s" % (phone_id, name))


def scan_pics(src, ignore=None):
    for subfile in src.iterdir():
        name = subfile.name
        if name and not name[0] in "._" and ignore and name not in ignore:
            if subfile.is_dir():
                yield from scan_pics(subfile, ignore=ignore)

            elif subfile.suffix.lower() in ".3gp .avi .gif .heic .jpg .jpeg .mov .mp4 .png .tif":
                yield subfile

            else:
                print("--> %s" % subfile)


def reorg_pics(path):
    path = os.path.expanduser(path)
    path = pathlib.Path(path)
    count = 0
    moved = 0
    skipped = 0
    same = 0
    import exifread
    import imghdr
    for item in scan_pics(path, ignore=("todo", )):
        if item.suffix.lower() in ".3gp .avi .mov .mp4":
            continue

        if item.suffix.lower() in ".heic":
            with open(item, "rb") as fh:
                tt = exifread.process_file(fh, details=False)
                if not tt:
                    print("--> check %s" % item)

            continue

        x = imghdr.what(item)
        if not x or x not in 'gif jpeg png tiff':
            print("--> check %s %s" % (x, item))

    for item in scan_pics(path / "todo", ignore=("PaxHeader", )):
        count += 1
        ss = item.stat()
        dd = min(ss.st_mtime, ss.st_ctime)
        dd = datetime.datetime.fromtimestamp(dd)
        relative_path = "%s/%s" % (dd.strftime("%Y/%m"), item.name)
        x = relative_path.split("/")
        assert len(x) == 3
        if not re.match(r"\d+/\d\d/[\w #-]+\.\w+", relative_path):
            print("--> invalid path %s [%s]" % (relative_path, item))
            continue
            # sys.exit(1)

        dest = path / relative_path
        if item != dest:
            if dest.exists():
                if filecmp.cmp(item, dest):
                    same += 1
                    print("--> removed %s" % item)
                    os.remove(item)
                    continue

                relative_path = "%s/x-%s" % (dd.strftime("%Y/%m"), item.name)
                dest2 = path / relative_path
                if dest2.exists():
                    if filecmp.cmp(item, dest2):
                        same += 1
                        print("--> removed-x %s" % item)
                        os.remove(item)
                        continue

                    skipped += 1
                    print("--> diff: %s - %s" % (item, dest))
                    continue

                else:
                    dest = dest2

            if not dest.parent.is_dir():
                os.makedirs(dest.parent)

            moved += 1
            print("Moved %s" % relative_path)
            shutil.move(item, dest)

    print("Moved %s / %s pics (%s skipped, %s same)" % (moved, count, skipped, same))


def to_ts(ts, fmt, pm="%p"):
    if " 00:" in ts:
        return datetime.datetime.strptime(ts, fmt + " %H:%M" + pm)

    return datetime.datetime.strptime(ts, fmt + " %I:%M" + pm)


def is_office_hours(ts):
    return 9 <= ts.hour <= 17


class Call:

    length = None

    def __init__(self, ab, timestamp, incoming, callee, length, dest=None, is_sms=None):
        self.ab = ab
        self.timestamp = timestamp
        self.incoming = incoming
        self.callee = callee
        self.length = int(length)
        self.recipient = ab.get_recipient(callee, canonical=True)
        self.office_hours = is_office_hours(self.timestamp)
        self.dest = dest  # ex: SAN JOSE
        self.is_sms = is_sms

    def __repr__(self):
        return "%s" % (self.recipient or self.callee)


def setrep(label, items):
    return "%s %s" % (len(items), label)


class CalleeRecap:
    def __init__(self, recipient):
        self.recipient = recipient
        self.calls = []

    @property
    def interactions(self):
        return len(self.calls)

    @property
    def phone_calls(self):
        return [c for c in self.calls if not c.is_sms]

    @property
    def sms_texts(self):
        return [c for c in self.calls if c.is_sms]

    @property
    def length(self):
        return sum(c.length for c in self.calls if c.length)

    def __lt__(self, other):
        return self.interactions < other.interactions

    def __repr__(self):
        res = []
        mins = self.length
        if mins:
            mins = " [%s m]" % mins

        res.append("%s calls%s" % (len(self.phone_calls), mins or ""))
        res.append("%s sms" % len(self.sms_texts))
        non_office = [c for c in self.calls if not c.office_hours]
        if non_office:
            res.append("%s at night" % len(non_office))

        return "%s: %s" %  (", ".join(res), self.recipient)

    def category_overview(self, items, category=None):
        incoming = [c for c in items if c.incoming]
        outcoming = [c for c in items if not c.incoming]
        info = []
        if category:
            info.append("; %s:" % category)

        if incoming:
            info.append(setrep("in", incoming))

        if outcoming:
            info.append(setrep("out", outcoming))

        return " ".join(info)

    def type_overview(self, label, items):
        info = []
        office = [c for c in items if c.office_hours]
        if office:
            info.append(self.category_overview(office))

        non_office = [c for c in items if not c.office_hours]
        if non_office:
            info.append(self.category_overview(non_office, category="night"))

        res = setrep(label, items)
        if info:
            res += " [%s]" % " ".join(info)

        return res

    def add_detail(self, result, label, items):
        if items:
            res = []
            total = 0
            by_day = defaultdict(list)
            for item in items:
                assert isinstance(item.timestamp, datetime.datetime)
                key = item.timestamp.strftime("%m-%d")
                if item.timestamp.weekday() in (5, 6):
                    key += "*"

                by_day[key].append(item)

            for day, day_items in sorted(by_day.items()):
                detail = []
                for item in day_items:
                    x = item.timestamp.strftime("%H:%M")
                    if not item.incoming:
                        x = "+%s" % x

                    if item.is_sms:
                        if "Pict" in item.is_sms:
                            x += "*"

                    if item.length:
                        x += " %sm" % item.length
                        total += item.length

                    detail.append(x)

                res.append("  %s: %s" % (day, ", ".join(detail)))

            result.append("%s:\n  %s" % (label, "\n  ".join(res)))

    def overview(self, detail):
        calls = [c for c in self.calls if not c.is_sms]
        sms = [c for c in self.calls if c.is_sms]
        res = "%s; %s" % (self.type_overview("calls", calls), self.type_overview("sms", sms))
        if detail:
            detail = []
            self.add_detail(detail, "call", [c for c in self.calls if not c.is_sms])
            self.add_detail(detail, "sms", [c for c in self.calls if c.is_sms])
            if detail:
                res = "%s\n  %s" % (res, "\n  ".join(detail))

        return res

    def display(self, detail):
        by_month = {}
        for c in sorted(self.calls, key=lambda x: x.timestamp):
            assert isinstance(c, Call)
            m = c.timestamp.strftime("%Y-%m")
            rr = by_month.get(m)
            if rr is None:
                rr = CalleeRecap(self.recipient)
                by_month[m] = rr

            rr.calls.append(c)

        for m, rr in sorted(by_month.items()):
            print("%s: %s total, %s" % (m, len(rr.calls), rr.overview(detail)))

        print("----")


class Callers:
    parser_headers = None
    current_parser = None

    def __init__(self, ab, recipient, start=None, end=None):
        self.ab = ab
        self.recipient = recipient
        self.by_callee = {}
        self.calls = []
        self.start = start and datetime.datetime.strptime(start, "%Y%m")
        self.end = end and datetime.datetime.strptime(end, "%Y%m")

    def __repr__(self):
        return "%s" % self.recipient

    def display(self, detail):
        for callee in sorted(self.by_callee.values(), key=lambda x: -x.interactions):
            if len(callee.recipient.phone_id) > 6:
                print(callee)
                callee.display(detail)

    def set_parser(self, parser, headers):
        self.parser_headers = [x.strip() for x in headers]
        self.current_parser = parser

    def do_parse(self, line):
        line = line.strip()
        c = self.current_parser(line)
        if not c:
            if c is None:
                self.current_parser = None

            return

        if (self.start is None or self.start < c.timestamp) and (self.end is None or self.end > c.timestamp):
            self.calls.append(c)

    def parse_csv_call(self, line):
        items = line.split(",")
        if len(items) == 1 or not items[0]:
            return None

        length = 0
        dest = None
        if len(items) == 13:
            dest = items[5]
            is_sms = None
            length = items[6]
            incoming = dest.startswith("INCOMING")

        else:
            is_sms = items[5]
            incoming = items[10] == "Rcvd"

        ts = "%s %s" % (items[2], items[3])
        timestamp = to_ts(ts, "%m/%d/%Y")
        callee = items[4]
        c = Call(self.ab, timestamp, incoming, callee, length, dest=dest, is_sms=is_sms)
        return c

    def parse_tsv_call(self, line):
        items = line.split("|")
        if len(items) < 5:
            return None

        # timestamp = datetime.datetime.strptime(items[1], "%m/%d/%Y %I:%M:%S %p")
        timestamp = to_ts(items[1], "%m/%d/%Y", pm=":%S %p")
        callee = items[2]
        dest = items[3]
        incoming = dest.startswith("INCOMING")
        if len(items) == 6:
            is_sms = None
            length = int(items[5])

        else:
            is_sms = items[4]
            length = 0

        c = Call(self.ab, timestamp, incoming, callee, length, dest=dest, is_sms=is_sms)
        return c

    def _get_callee_recap(self, r):
        recap = self.by_callee.get(r)
        if recap is None:
            recap = CalleeRecap(r)
            self.by_callee[r] = recap

        return recap

    def finalize(self):
        for c in self.calls:
            recap = self._get_callee_recap(c.recipient)
            recap.calls.append(c)


class CurrentPeriod:
    def __init__(self, recipient):
        self.recipient = recipient
        self.by_type = defaultdict(int)
        self.total = 0
        self.length = 0
        self.calls = []

    def __repr__(self):
        return "%s %s" % (self.total, self.recipient)

    def add_call(self, items):
        self.calls.append(items)
        key = items[4]
        if "Messaging" not in key:
            key = "in" if items[4] == "INCOMING" else "out"
            self.length += int(items[6])

        ts = "2022/%s %s" % (items[1], items[2])
        ts = to_ts(ts, "%Y/%m/%d", pm=" %p")
        if not is_office_hours(ts):
            key = "night %s" % key

        self.total += 1
        self.by_type[key] += 1


def show_call_log(target):
    t, _, start = target.partition(":")
    detail = t.startswith("+")
    start, _, end = start.partition(":")
    ab = AddressBook(CCPATH)
    path = os.path.join(CCPATH, "call-log")
    callers = {}
    current_period = {}
    target = ab.get_recipient(t, canonical=True)
    for fname in os.listdir(path):
        if not fname.endswith(".csv") and not fname.endswith(".tsv"):
            continue

        current = None
        with open(os.path.join(path, fname)) as fh:
            line_number = 0
            for line in fh:
                line_number += 1
                line = line.rstrip()
                if not line or ",Data Transfer," in line or ",Intl Rated as Domestic," in line:
                    continue

                if line.startswith("Mobile Number:") or line.startswith("PhoneNumber :"):
                    _, _, nb = line.partition(":")
                    nb = nb.strip().strip(",")
                    r = ab.get_recipient(nb, canonical=True)
                    assert r
                    current = callers.get(r)
                    if current is None:
                        current = Callers(ab, r, start=start or None, end=end or None)
                        callers[r] = current

                    continue

                if current is None or current.recipient.phone_id != target.phone_id:
                    continue

                if current.current_parser:
                    current.do_parse(line)
                    continue

                if line.startswith("Item,Day,Date,Time"):
                    current.set_parser(current.parse_csv_call, line.split(","))
                    continue

                if line.startswith("SNO | Date & Time"):
                    current.set_parser(current.parse_tsv_call, line.split("|"))
                    continue

    t = callers[target]
    t.finalize()
    t.display(detail)
    if current_period:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("src")
    parser.add_argument("--genonly", "-g", action="store_true")
    parser.add_argument("--limit", "-l", type=int)
    args = parser.parse_args()
    src = args.src
    if src and (src.startswith("+1") or src.startswith("1")):
        show_call_log(src)
        sys.exit(0)

    if src and src.endswith(".csv"):
        ib = IBChats(src)
        ib.process_csv()
        sys.exit(0)

    if src and src.endswith(".txt"):
        ib = IBChats(src)
        ib.process_txt()
        sys.exit(0)

    if src and src.startswith("g:"):
        gpd = Gpd()
        gpd.display_coords(src[2:])
        sys.exit(0)

    if src and src.startswith("s:"):
        sort_photos(src[2:])
        sys.exit(0)

    if src and src.startswith("c:"):
        check_vcf(src[2:])
        sys.exit(0)

    if src and src.startswith("p:"):
        reorg_pics(src[2:])
        sys.exit(0)

    if src and len(src) < 2:
        base = "/Users"
        for x in os.listdir(base):
            if x.startswith(src):
                src = os.path.join(base, x, "Library/Messages")
                break

    chats = AllChats(src)
    if not chats.msg_count:
        sys.exit(0)

    chats.genhtml(limit=args.limit)
    if not args.genonly:
        today = datetime.datetime.today()
        with open(chats.pivot_path, "wt") as fh:
            fh.write("%s %s %s\n" % (today.year, today.month, today.day))

        tp = os.path.join(chats.mhpath, "_c.txt")
        with open(tp, "wt") as fh:
            fh.write(chats.as_text())

        os.chdir(CCPATH)
        tarp = "mh-%s.tar.gz" % today.strftime("%Y-%m-%d")
        run_program("/usr/bin/tar", "zcf", tarp, "mh")
        user = os.environ.get("SUDO_USER" if os.geteuid() == 0 else "USER")
        if user:
            run_program("chown", user, tarp)

        shutil.rmtree(chats.mhpath)
        shutil.rmtree(chats.tmp_path)


if __name__ == "__main__":
    main()
