#!/usr/bin/python3

import argparse
import base64
import datetime
import os
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
HTML_HEAD = """
<html>
<head>
<meta charset="UTF-8">
<style>
body { width: 700; }
.dt { font-size: 10pt; color: darkgray; }
.day { font-size: 11pt; margin: 5px; color: darkgray; text-align: center; }
.number { font-size: 13pt; color: darkgray; }
.other { text-align: left; margin: 0px; }
.mine { text-align: right; margin: 0px; color: darkblue; }
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

    def save(self, path, all_chats=None):
        with open(path, "wt") as fh:
            fh.write("%s\n" % HTML_HEAD.strip())
            if self.title:
                fh.write("<h1>%s</h1>\n" % self.title)

            ld = None
            for msg in self.messages:
                if ld != msg.day:
                    ld = msg.day
                    ts = msg.date.strftime("%a %Y-%m-%d")
                    fh.write('<p class="day">%s</p>\n' % ts)

                fh.write(msg.html_representation(all_chats))

            fh.write("</body></html>\n")


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

    def __init__(self, phone_id, name=None):
        self.phone_id = phone_id
        self.has_name = bool(name)
        self.id = phone_id.strip("+").lstrip("1")
        self.name = name or self.id
        self.fname = RX_FNAME.sub(".", self.name.lower())

    def __repr__(self):
        if self.has_name:
            return "%s %s" % (self.name, self.id)

        return self.id


class AddressBook:

    def __init__(self, path):
        self.path = self.find_ab(path)
        self.phone_map = {}
        if self.path:
            with open(os.path.expanduser(self.path)) as fh:
                for line in fh:
                    t, _, n = line.partition(" ")
                    t = t.strip()
                    n = n.strip()
                    if t and n:
                        self.phone_map[t] = Recipient(t, name=n)

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

    def get_recipient(self, cid):
        r = self.phone_map.get(cid)
        return r or Recipient(cid)


class AllChats:

    def __init__(self, mpath):
        self.mpath = os.path.expanduser(mpath)
        self.ccpath = os.path.expanduser("~/tmp/cc")
        self.mhpath = os.path.join(self.ccpath, "mh")
        self.pivot_path = os.path.join(self.ccpath, ".p")
        self.tmp_path = os.path.join(self.ccpath, "_tmp")
        mkdir(self.tmp_path)
        mkdir(self.mhpath)
        self.db = sqlite3.connect(os.path.join(self.mpath, "chat.db"))
        self.chats = {}
        self.address_book = AddressBook(self.ccpath)
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


def ibackup(path):
    line_number = 0
    current_msg = None
    html = Html()
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            line_number += 1
            if (line_number <=1) or (not line and not current_msg):
                continue

            if len(line) > 30 and line.startswith('"'):
                i = line.index('"', 1)
                dt = line[1:i]
                dt = datetime.datetime.strptime(dt, "%A, %b %d, %Y  %H:%M")
                line = line[i + 2:]
                sender, _, line = line.partition(",")
                _, _, line = line.partition(",")
                imsg, _, line = line.partition(",")
                assert not imsg
                if current_msg is None:
                    current_msg = Message()

                current_msg.date = dt
                current_msg.day = (dt.year, dt.month, dt.day)
                current_msg.is_from_me = sender == "+19253236663"
                if line.startswith('"'):
                    current_msg.text = line[1:]

                else:
                    current_msg.text = line
                    html.add_msg(current_msg)
                    current_msg = None

            elif line.endswith('"'):
                current_msg.text += "<br>\n%s" % line[:-1]
                html.add_msg(current_msg)
                current_msg = None

            else:
                current_msg.text += "<br>\n%s" % line

    dest = "%s.html" % path[:-4]
    html.save(dest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("src")
    parser.add_argument("--genonly", action="store_true")
    parser.add_argument("--limit", "-l", type=int)
    args = parser.parse_args()
    src = args.src
    if src and src.endswith(".csv"):
        ibackup(os.path.expanduser(src))
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

        os.chdir(chats.ccpath)
        tarp = "mh-%s.tar.gz" % today.strftime("%Y-%m-%d")
        run_program("/usr/bin/tar", "zcf", tarp, "mh")
        user = os.environ.get("SUDO_USER" if os.geteuid() == 0 else "USER")
        if user:
            run_program("chown", user, tarp)

        shutil.rmtree(chats.mhpath)
        shutil.rmtree(chats.tmp_path)


if __name__ == "__main__":
    main()
