# -*- coding: utf-8 -*-

import tempfile
import re
import markdown
import pygments # for markdown code highlighting
import os
import sys
import smtplib
import time
import logging
import threading

from datetime import datetime, timezone
from email.message import EmailMessage
from email.headerregistry import Address
from email.utils import make_msgid
from slacker import Slacker

from core.utils.filesystem import Filesystem

class Report():
    """Logging and reporting"""
    
    _slack = None
    _slack_token = os.getenv("SLACK_TOKEN", None)
    _slack_authed = None
    _slack_channel = os.getenv("SLACK_CHANNEL", "#test")
    
    stdout_verbosity = 'INFO'
    pipeline = None
    title = None
    should_email = True
    _report_dir = None
    _messages = None
    
    _i18n = {
        "Links": "Lenker",
        "none": "ingen"
    }
    
    def __init__(self, pipeline):
        self._messages = {
            "message": [],
            "attachment": []
        }
        self.pipeline = pipeline
        logging.basicConfig(stream=sys.stdout)
    
    def reportDir(self):
        # Lag rapport-mappe
        if not self._report_dir:
            report_dir = self.pipeline.book["name"]
            report_dir += "-"
            report_dir += datetime.now(timezone.utc).strftime("%F_%H-%M-%S.") + str(round((time.time() % 1) * 1000)).zfill(3)
            report_dir += "-"
            report_dir += self.pipeline.uid
            report_dir = os.path.join(self.pipeline.dir_reports, report_dir)
            os.makedirs(report_dir)
            self._report_dir = report_dir
        return self._report_dir
    
    def add_message(self, severity, message, message_type="message", add_empty_line_last=True, add_empty_line_between=False):
        if severity == "DEBUG":
            logging.debug("[" + Report.thread_name(self.pipeline) + "] " + message)
        elif severity == "INFO":
            logging.info("[" + Report.thread_name(self.pipeline) + "] " + message)
        elif severity == "SUCCESS":
            logging.info("[" + Report.thread_name(self.pipeline) + "] " + message)
        elif severity == "WARN":
            logging.warn("[" + Report.thread_name(self.pipeline) + "] " + message)
        elif severity == "ERROR":
            logging.error("[" + Report.thread_name(self.pipeline) + "] " + message)
        else:
            logging.warn("[" + Report.thread_name(self.pipeline) + "] Unknown message severity: " + str(severity))
            logging.warn("[" + Report.thread_name(self.pipeline) + "] " + message)
        
        lines = None
        if isinstance(message, list):
            lines = message
        else:
            lines = [ message ]
        
        if message_type not in self._messages:
            self._messages[message_type] = []
        
        lines = [l for line in lines for l in line.split("\n")]
        if add_empty_line_between:
            spaced_lines = []
            for line in lines:
                spaced_lines.append(line)
                spaced_lines.append("")
            lines = spaced_lines
        if add_empty_line_last:
            lines.append("")
        
        for line in lines:
            self._messages[message_type].append({ 'time': time.strftime("%Y-%m-%d %H:%M:%S"), 'severity': severity, 'text': line })
    
    @staticmethod
    def thread_name(pipeline=None):
        if pipeline and pipeline.title:
            return pipeline.title
        if threading.get_ident() == threading.main_thread():
            return "Main thread"
        return str(threading.get_ident())
    
    def debug(self, message, message_type="message", add_empty_line_last=True):
        self.add_message('DEBUG', message, message_type, add_empty_line_last)
    
    def info(self, message, message_type="message", add_empty_line_last=True):
        self.add_message('INFO', message, message_type, add_empty_line_last)
    
    def success(self, message, message_type="message", add_empty_line_last=True):
        self.add_message('SUCCESS', message, message_type, add_empty_line_last)
    
    def warn(self, message, message_type="message", add_empty_line_last=True):
        self.add_message('WARN', message, message_type, add_empty_line_last)
    
    def error(self, message, message_type="message", add_empty_line_last=True):
        self.add_message('ERROR', message, message_type, add_empty_line_last)
    
    @staticmethod
    def emailPlainText(subject, message, smtp, sender, recipients):
        assert subject
        assert message
        assert smtp
        assert sender
        assert recipients
        
        # 1. build e-mail
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = recipients if isinstance(recipients, Address) else tuple(recipients)
        msg.set_content(message)
        
        # 2. send e-mail
        if smtp["host"] and smtp["port"]:
            with smtplib.SMTP(smtp["host"] + ":" + smtp["port"]) as s:
                s.ehlo()
                s.starttls()
                if smtp["user"] and smtp["pass"]:
                    s.login(smtp["user"], smtp["pass"])
                else:
                    logging.debug("[" + Report.thread_name() + "] email user/pass not configured")
                s.send_message(msg)
        else:
            logging.warn("[" + Report.thread_name() + "] email host/port not configured")
        
        Report.slack(text=subject, attachments=None)
    
    def email(self, smtp, sender, recipients, subject=None):
        assert smtp
        assert sender
        assert recipients
        
        if not subject:
            subject = self.title if self.title else self.pipeline.title
        
        # 0. Create attachment with complete log (including DEBUG statements)
        self.attachLog()
        
        # Determine overall status
        status = "INFO"
        for message_type in self._messages:
            for m in self._messages[message_type]:

                if m["severity"] == "SUCCESS" and status in [ "INFO" ]:
                    status = "SUCCESS"
                elif m["severity"] == "WARN" and status in [ "INFO", "SUCCESS" ]:
                    status = "WARN"
                elif m["severity"] == "ERROR":
                    status = "ERROR"
        
        
        # 1. join lines with severity SUCCESS/INFO/WARN/ERROR
        markdown_text = []
        for m in self._messages["message"]:
            if m['severity'] != 'DEBUG':
                markdown_text.append(m['text'])
        markdown_text.append("\n----\n")
        markdown_text.append("\n# "+self._i18n["Links"]+"\n")
        markdown_text.append("\n<ul style=\"list-style: none;\">")
        
        # Pick icon and style for INFO-attachments
        attachment_styles = {
            "DEBUG": {
                "icon": "🗎",
                "style": ""
            },
            "INFO": {
                "icon": "🛈",
                "style": ""
            },
            "SUCCESS": {
                "icon": "😄",
                "style": "background-color: #bfffbf;"
            },
            "WARN": {
                "icon": "😟",
                "style": "background-color: #ffffbf;"
            },
            "ERROR": {
                "icon": "😭",
                "style": "background-color: #ffbfbf;"
            }
        }
        
        attachments = []
        for m in self._messages["attachment"]:
            smb, file, unc = Filesystem.networkpath(m["text"])
            relpath = os.path.relpath(m["text"], self.pipeline.dir_base)
            if m["text"].startswith(self.reportDir()):
                relpath = os.path.relpath(m["text"], self.reportDir())
            attachments.append({
                "title": relpath + ("/" if os.path.isdir(m["text"]) else ""),
                "smb": smb,
                "file": file,
                "unc": unc,
                "severity": m["severity"]
            })
        for attachment in attachments:
            # UNC links seems to be preserved when viewed in Outlook.
            # file: and smb: URIs are disallowed or removed.
            # So these links will only work in Windows.
            # If we need this to work cross-platform, we would have
            # to map the network share paths to a web server so that
            # the transfers go through http:. This could maybe be mapped
            # using environment variables.
            li = "<li>"
            li += "<span style=\"vertical-align: middle; font-size: 200%;\">" + attachment_styles[attachment["severity"]]["icon"] + "</span> "
            li += "<span style=\"vertical-align: middle; " + attachment_styles[attachment["severity"]]["style"] + "\">"
            li += "<a href=\"" + attachment["unc"] + "\">" + attachment["title"] + "</a></sup>"
            li += "</span>"
            li += "</li>"
            markdown_text.append(li)
        markdown_text.append("</ul>\n")
        markdown_text = "\n".join(markdown_text)
        
        # 2. parse string as Markdown and render as HTML
        markdown_html = markdown.markdown(markdown_text, extensions=['fenced_code', 'codehilite'])
        markdown_html = '''<!DOCTYPE html>
<html>
<head>
<meta charset=\"utf-8\"/>
<title>"+subject+"</title>
</head>
<body>
''' + markdown_html + '''
</body>
</html>
'''
        
        # 3. build e-mail
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = recipients if isinstance(recipients, Address) else tuple(recipients)
        msg.set_content(markdown_text)
        msg.add_alternative(markdown_html, subtype="html")
        
        # 4. send e-mail
        if smtp["host"] and smtp["port"]:
            with smtplib.SMTP(smtp["host"] + ":" + smtp["port"]) as s:
                s.ehlo()
                s.starttls()
                if smtp["user"] and smtp["pass"]:
                    s.login(smtp["user"], smtp["pass"])
                else:
                    logging.debug("[" + Report.thread_name(self.pipeline) + "] email user/pass not configured")
                s.send_message(msg)
        else:
            logging.warn("[" + Report.thread_name(self.pipeline) + "] email host/port not configured")
        
        with open('/tmp/email.md', "w") as f:
            f.write(markdown_text)
            logging.debug("[" + Report.thread_name(self.pipeline) + "] email markdown: /tmp/email.md")
        with open('/tmp/email.html', "w") as f:
            f.write(markdown_html)  
            logging.debug("[" + Report.thread_name(self.pipeline) + "] email html: /tmp/email.html")
        
        # 5. send message to Slack
        slack_attachments = []
        for attachment in attachments:
            color = None
            if attachment["severity"] == "SUCCESS":
                color = "good"
            elif attachment["severity"] == "WARN":
                color = "warning"
            elif attachment["severity"] == "ERROR":
                color = "danger"
            slack_attachments.append({
                "title_link": attachment["smb"],
                "title": attachment["title"],
                "fallback": attachment["title"],
                "color": color
            })
        Report.slack(text=subject, attachments=slack_attachments)
    
    @staticmethod
    def slack(text, attachments):
        assert not text or isinstance(text, str)
        assert not attachments or isinstance(attachments, list)
        assert text or attachments
        
        if Report._slack_authed is None or Report._slack is None:
            Report._slack = Slacker(os.getenv("SLACK_TOKEN"))
            try:
                auth = Report._slack.auth.test()
                if auth.successful:
                    logging.info("[" + Report.thread_name() + "] Slack authorized as \"" + auth.body.get("user") + "\" as part of the team \"" + auth.body.get("team") + "\"")
                    Report._slack_authed = True
                else:
                    logging.warn("[" + Report.thread_name() + "] Failed to authorize to Slack")
                    Report._slack_authed = False
                
            except Exception:
                logging.exception("[" + Report.thread_name() + "] Failed to authorize to Slack")
                Report._slack_authed = False
        
        if Report._slack_authed is not True:
            logging.warn("[" + Report.thread_name() + "] Not authorized to send messages to Slack")
        
        Report._slack.chat.post_message(channel=Report._slack_channel, as_user=True, text=text, attachments=attachments)
    
    def attachLog(self):
        logpath = os.path.join(self.reportDir(), "log.txt")
        self.attachment([m["text"] for m in self._messages["message"]], logpath, "DEBUG")
        return logpath
    
    def infoHtml(self, html, message_type="message"):
        """ wash the HTML before reporting it """
        
        if isinstance(html, list):
            html = "\n".join(html)
        html = re.sub("^.*<body[^>]*>", "", html, flags=re.DOTALL)
        html = re.sub("</body.*$", "", html, flags=re.DOTALL)
        html = re.sub("<script[^>]*(/>|>.*?</script>)", "", html, flags=re.DOTALL)
        html = "\n".join([line.strip() for line in html.split("\n")])
        self.info(html)
    
    def attachment(self, content, path, severity):
        assert path and os.path.isabs(path), "Links must have an absolute path."
        assert not content or isinstance(content, list) or isinstance(content, str), "Attachment content must be a string or list when given."
        
        if path in [m["text"] for m in self._messages["attachment"]]:
            self.debug("Skipping attachment; tried attaching same attachment twice: " + path)
            return
        
        if content:
            if isinstance(content, list):
                content = "\n".join(content)
            with open(path, "a") as f:
                f.write(content)
        if severity == "DEBUG":
            self.info(path, message_type="attachment", add_empty_line_last=False)
        elif severity == "INFO":
            self.info(path, message_type="attachment", add_empty_line_last=False)
        elif severity == "SUCCESS":
            self.success(path, message_type="attachment", add_empty_line_last=False)
        elif severity == "WARN":
            self.warn(path, message_type="attachment", add_empty_line_last=False)
        else: # "ERROR"
            self.error(path, message_type="attachment", add_empty_line_last=False)
    
    # in case you want to override something
    def translate(self, english_text, translated_text):
        self._i18n[english_text] = translated_text

class DummyReport(Report):
    pipeline = None
    
    def add_message(self, severity, message, message_type, add_empty_line_last, add_empty_line_between):
        pass
