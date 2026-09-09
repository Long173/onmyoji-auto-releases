# uncompyle6 version 3.9.3
# Python bytecode version base 3.6 (3379)
# Decompiled from: Python 3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
# Embedded file name: realm.py
# Compiled at: 2021-09-22 16:15:28
# Size of source mod 2**32: 30688 bytes
from logging import fatal
import threading, keyboard
from win32api import PostMessage
from GameControl import *
import os, pyautogui
from ThreadGame import *
from Util import *
CLAIM_REWARD = (566, 541)
CHANGE_SHIKI_COORDINATE = (468, 374)
SLIDE_STORY_COORDINATE = [(200, 200), (1000, 200)]
SHIKI_LEVEL_COORDINATE = (52, 580)
SLIDE_CHANGE_SHIKI = [(600, 500), (870, 500)]
REGION_FIND_FULL_EXP_LEADER = [(0, 0), (300, 600)]
REGION_CHANGE_FULL_EXP_LEADER = [(600, 0), (1100, 300)]
REGION_CHANGE_FULL_EXP_PASENGER = [(0, 0), (1108, 402)]
REGION_FIND_FULL_EXP_SOLO = [(0, 0), (520, 600)]
REGION_CHANGE_EXP_SOLO = [(387, 61), (1105, 374)]
CHANGE_FOOD_RIGHT_COORDINATE = (938, 301)
CHANGE_FOOD_MIDDLE_COORDINATE = (553, 300)
CHANGE_FOOD_LEFT_COORDINATE = (157, 288)
CHANGE_FOOD_LEADER_RIGHT_COORDINATE = (826, 261)
REFRESH_SEAL_COORDINATE = (438, 551)
CHOOSE_LEVEL_HARD_COORDINATE = (409, 195)
CHOOSE_FRIEND_COORDINATE = (452, 95)
SLIDE_FRIENDLIST = [(493, 246), (525, 436)]
INVITE_MEMBER_COORDINATE = (681, 504)
TEAM_COORDINATE = (569, 492)
STORY_BACK_COORDINATE = (35, 51)
STORY_OK_COORDINATE = (681, 351)
OK_SOUL_DIALOG_COORDINATE = (679, 375)
CHECKBOX_COORDINATE = (390, 300)
SOUL_ICON_COORDINATE = (173, 584)
INVITE_SOUL_ONLY_COORDINATE = (670, 445)
SLIDE_LEVEL_OROCHI = [(276, 137), (271, 505)]
CREATE_TEAM_SOUL_COORDINATE = (868, 564)
REGION_TEAM_INVITE_SOUL = [(0, 0), (729, 409)]
START_SOUL_COORDINATE = (1075, 565)
INVITE_MEMBER_SOUL_COORDINATE = (681, 506)
SLIDE_FRIEND_LIST_SOUL = [(428, 169), (431, 440)]
TARGET1 = (87, 394)
TARGET2 = (320, 355)
TARGET3 = (532, 336)
TARGET4 = (729, 339)
TARGET5 = (904, 424)
IMAGE_FAILED_PATH = "./screenshots/failed.png"
IMAGE_SCREENSHOT_PATH = "./screenshots/screenshot.png"
IMAGE_CONNECTING_PATH = "./screenshots/connecting.png"
IMAGE_ASSISTANCE_PATH = "./screenshots/accept_wantedquest.png"
IMAGE_ASSISTANCE_2_PATH = "./screenshots/close.png"
IMAGE_ACCEPT_PATH = "./screenshots/accept.png"
IMAGE_ACCEPT_PATH_WANTED_QUEST = "./screenshots/accept_wantedquest.png"
IMAGE_OCCUPIED_PATH = "./screenshots/occupied.png"
IMAGE_FOOD_INSUFFICIENCY_PATH = "./screenshots/food.png"
IMAGE_CLOSE_DIALOG_PATH = "./screenshots/close.png"
IMAGE_DISCONNECTED_PATH = "./screenshots/disconnected.png"
IMAGE_CLICK_PATH = "./screenshots/RealmRaid/click.png"
IMAGE_TAP_PATH = "./screenshots/RealmRaid/tap.png"
IMAGE_REALM_COOLDOWN_PATH = "./screenshots/RealmRaid/cooldown.png"
# Khi match qua tap.png, bot click vao nut Ready o goc duoi-phai (toa do co dinh)
TAP_READY_BUTTON = (1033, 547)
# Goc trai-tren de dong popup "Cooldown time is not yet up!"
COOLDOWN_DISMISS_POSITION = (10, 10)
IMAGE_REFUSE_PATH = "./screenshots/refuse.png"
IMAGE_SOUL_INVITE_PATH = "./screenshots/Soul/teamInvite.png"
IMAGE_SOUL_START_PATH = "./screenshots/Soul/start.png"
IMAGE_SOUL_FINISHED1_PATH = "./screenshots/Soul/finished1.png"
IMAGE_SOUL_FINISHED2_PATH = "./screenshots/Soul/finished2.png"
IMAGE_SOUL_INVITE_DIALOG_PATH = "./screenshots/Soul/inviteDialog.png"
IMAGE_SOUL_INVITE_CHECKBOX_PATH = "./screenshots/Soul/invitecheckbox.png"
IMAGE_SOUL_INVITE_CONFIRM_PATH = "./screenshots/Soul/inviteconfirm.png"
IMAGE_SOUL_SUSI_PATH = "./screenshots/Soul/susi.png"
IMAGE_SOUL_ICON_PATH = "./screenshots/Soul/soul.png"
IMAGE_SOUL_OROCHI_PATH = "./screenshots/Soul/orochi.png"
IMAGE_SOUL_OROCHI_STAGE10_PATH = "./screenshots/Soul/stage10.png"
IMAGE_SOUL_TEAM_PATH = "./screenshots/Soul/team.png"
IMAGE_SOUL_STAGE10_DIALOG_PATH = "./screenshots/Soul/stage10TeamDialog.png"
IMAGE_SOUL_CREATE_TEAM_PATH = "./screenshots/Soul/createTeam.png"
IMAGE_SOUL_CREATE_ROOM_PATH = "./screenshots/Soul/createRoom.png"
IMAGE_SOUL_STAGE10_FOCUS_PATH = "./screenshots/Soul/stage10Focus.png"
IMAGE_SOUL_INROOM_PATH = "./screenshots/Soul/inroom.png"
IMAGE_SOUL_STAT_PATH = "./screenshots/Soul/stat.png"
IMAGE_SOUL_SET_PATH = "./screenshots/Soul/set.png"
IMAGE_SOUL_CLOCL_PATH = "./screenshots/Soul/clock.png"
IMAGE_SOULD_ACCEPT_PATH = "./screenshots/Soul/accept.png"
IMAGE_STORY_INVITE_PATH = "./screenshots/Story/invite.png"
IMAGE_STORY_INVITATION_CONFIRMED_PATH = "./screenshots/Story/invitationconfirmed.png"
IMAGE_STORY_START_PATH = "./screenshots/Story/start.png"
IMAGE_STORY_FIGHT_PATH = "./screenshots/Story/fight.png"
IMAGE_STORY_FIGHT_BOSS_PATH = "./screenshots/Story/fightBoss.png"
IMAGE_STORY_FINISHED1_PATH = "./screenshots/Story/finished1.png"
IMAGE_STORY_FINISHED2_PATH = "./screenshots/Story/finished2.png"
IMAGE_STORY_ACCEPT_PATH = "./screenshots/Story/accept.png"
IMAGE_STORY_BACK_PATH = "./screenshots/Story/back.png"
IMAGE_STORY_GET_REWARD_PATH = "./screenshots/Story/getReward.png"
IMAGE_STORY_REWARD_CONFIRMED_PATH = "./screenshots/Story/rewardconfirmed.png"
IMAGE_STORY_READY_PATH = "./screenshots/Story/ready.png"
IMAGE_STORY_READY_MARK_PATH = "./screenshots/Story/readyMark.png"
IMAGE_STORY_SELECT_LEVEL_PATH = "./screenshots/Story/selectLevel.png"
IMAGE_STORY_FULL1_PATH = "./screenshots/Story/full3.png"
IMAGE_STORY_FULL2_PATH = "./screenshots/Story/full4.png"
IMAGE_STORY_FOOD_PATH = "./screenshots/Story/food.png"
IMAGE_STORY_CHERRY_CAKE_PATH = "./screenshots/Story/cherryCake.png"
IMAGE_STORY_SHIKIGAMI_SELECTED_PATH = "./screenshots/Story/shikigamiSelected.png"
IMAGE_STORY_SHIKIGAMI_SELECTED1_PATH = "./screenshots/Story/shikigamiSelected1.png"
IMAGE_STORY_SHIKIGAMI_SELECTED3_PATH = "./screenshots/Story/shikigamiSelected2.png"
IMAGE_STORY_SHIKIGAMI_SELECTED2_PATH = "./screenshots/Story/shikigamiSelected6.png"
IMAGE_STORY_SHIKIGAMI_SELECTED8_PATH = "./screenshots/Story/shikigamiSelected8.png"
IMAGE_STORY_SELECTED_LEVEL_PATH = "./screenshots/Story/selectedLevel.png"
IMAGE_STORY_TEAM_PATH = "./screenshots/Story/team.png"
IMAGE_STORY_TEAMMATE_PATH = "./screenshots/Story/teammate.png"
IMAGE_STORY_APPROVE_PATH = "./screenshots/Story/approve.png"
IMAGE_STORY_SEAL_TICKET_PATH = "./screenshots/Story/sealticket.png"
IMAGE_STORY_LIST_CHAPTER_PATH = "./screenshots/Story/listchapter.png"
IMAGE_STORY_SPIRIT_PATH = "./screenshots/Story/spirit.png"
IMAGE_STORY_ISINTEAM_PATH = "./screenshots/Story/lead1.png"
IMAGE_STORY_CREATE_PATH = "./screenshots/Story/create.png"
IMAGE_STORY_EXP_PATH = "./screenshots/Story/exp.png"
IMAGE_STORY_OUT1_PATH = "./screenshots/Story/out1.png"
IMAGE_STORY_QUIT_PATH = "./screenshots/Story/quit.png"
IMAGE_SOUL_X_START_PATH = "./screenshots/SoulX/start.png"
IMAGE_SOUL_X_FINISHED1_PATH = "./screenshots/SoulX/finished1.png"
IMAGE_SOUL_X_FINISHED2_PATH = "./screenshots/SoulX/finished2.png"
IMAGE_SOUL_SOUGENBI_CHALLENGE = "./screenshots/Soul/sougenbiChallenge.png"
IMAGE_REALM_START_PATH = "./screenshots/RealmRaid/start.png"
IMAGE_REALM_SECTION_PATH = "./screenshots/RealmRaid/section.png"
IMAGE_REALM_RANK_PATH = "./screenshots/RealmRaid/rank.png"
IMAGE_REALM_FINISHED1_PATH = "./screenshots/RealmRaid/finished1.png"
IMAGE_REALM_FINISHED2_PATH = "./screenshots/RealmRaid/finished2.png"
IMAGE_REALM_SHIKIGAMI_SELECTED_PATH = "./screenshots/RealmRaid/shikigamiSelected.png"
IMAGE_REALM_SELECTION_MARK_PATH = "./screenshots/RealmRaid/selectionMark.png"
IMAGE_REALM_FAILED_PATH = "./screenshots/RealmRaid/failed.png"
IMAGE_REALM_RAID_PATH = "./screenshots/RealmRaid/realmRaid.png"
IMAGE_REALM_PROFILE_PATH = "./screenshots/RealmRaid/profile.png"
IMAGE_REALM_PRESET_PATH = "./screenshots/RealmRaid/preset.png"
IMAGE_REALM_REFRESH_PATH = "./screenshots/RealmRaid/refresh.png"
IMAGE_REALM_LOCK_PATH = "./screenshots/RealmRaid/lock.png"
IMAGE_REALM_EMPTY_TICKET = "./screenshots/RealmRaid/empty.png"
IMAGE_REALM_BATTLE_PATH = "./screenshots/RealmRaid/battle.png"
IMAGE_REALM_OK_PATH = "./screenshots/RealmRaid/ok.png"
IMAGE_REALM_FROG_PATH = "./screenshots/RealmRaid/frog.png"
IMAGE_SEAL_TEAM_PATH = "./screenshots/Seal/team.png"
IMAGE_SEAL_SEAL_PATH = "./screenshots/Seal/seal.png"
IMAGE_SEAL_MATCH_PATH = "./screenshots/Seal/match.png"
IMAGE_SEAL_START_PATH = "./screenshots/Seal/start.png"
IMAGE_SEAL_READY_PATH = "./screenshots/Seal/ready.png"
IMAGE_SEAL_FINISHED1_PATH = "./screenshots/Seal/finished1.png"
IMAGE_SEAL_FINISHED2_PATH = "./screenshots/Seal/finished2.png"
IMAGE_SEAL_ALL_PATH = "./screenshots/Seal/all.png"
IMAGE_SEAL_JOIN_PATH = "./screenshots/Seal/join.png"
IMAGE_SEAL_REFRESH_PATH = "./screenshots/Seal/refresh.png"
IMAGE_SEAL_WAIT_PATH = "./screenshots/Seal/wait.png"
IMAGE_SEAL_MATCH_PATH = "./screenshots/Seal/match.png"
IMAGE_COOP_SEAL = "./screenshots/coopwanted.png"
IMAGE_START_FIGHT = "./screenshots/Event/fight.png"
IMAGE_TARGET_SHIKIGAMI = "./screenshots/Event/target.png"
IMAGE_DEVILS_NIGHT_ENTER_PATH = "./screenshots/DemonParade/enter.png"
IMAGE_DEVILS_NIGHT_SELECTED_PATH = "./screenshots/DemonParade/selected.png"
IMAGE_DEVILS_NIGHT_START_PATH = "./screenshots/DemonParade/start.png"
IMAGE_DEVILS_NIGHT_BULLET_PATH = "./screenshots/DemonParade/bullet.png"
IMAGE_DEVILS_NIGHT_UP_PATH = "./screenshots/DemonParade/up.png"
IMAGE_DEVILS_NIGHT_OVER_PATH = "./screenshots/DemonParade/over.png"
IMAGE_DEVILS_NIGHT_INVITE_PATH = "./screenshots/DemonParade/invite.png"
IMAGE_DEVILS_NIGHT_SECTION_PATH = "./screenshots/DemonParade/section.png"
IMAGE_EVENT_CHALL_PATH = "./screenshots/Event/challenge.png"
IMAGE_EVENT_CONFIRM_PATH = "./screenshots/Event/confirm.png"
IMAGE_EVENT_CLAIM_PATH = "./screenshots/Event/claim.png"
IMAGE_EVENT_CAST_PATH = "./screenshots/Event/cast.png"
IMAGE_EVENT_READY_PATH = "./screenshots/Event/ready.png"
IMAGE_EVENT_FLAG = "./screenshots/Event/flag.png"
IMAGE_EVENT_FLAG1 = "./screenshots/Event/flag2.png"
IMAGE_EVENT_FLAG2 = "./screenshots/Event/flag3.png"
IMAGE_EVENT_SKILL1 = "./screenshots/Event/skill1.png"
IMAGE_EVENT_SKILL3 = "./screenshots/Event/skill3.png"
IMAGE_EVENT_TARGET = "./screenshots/Event/target.png"
IMAGE_EVENT_GATE = "./screenshots/Event/gate.png"
PLAY_TOGETHER_CONFIRM_PATH = "./screenshots/playtogether/confirm.png"
PLAY_TOGETHER_PLAY_PATH = "./screenshots/playtogether/play.png"
PLAY_TOGETHER_SAVE_PATH = "./screenshots/playtogether/save.png"
_localVariable = threading.local()
_DETECTION_INTERVAL = 0.2
_accountCount = 0
_phoban = 28
_vitri = 0
_fullShikigamiCount = 0
_isPaused = False
_isFullTeam = False
_detectExitThread = threading.Thread()
_accountLocker = threading.Lock()
_replaceShikigamiIfFull = True
_localVariable = threading.local()
_DETECTION_INTERVAL = 0.2
_accountCount = 0
_phoban = 28
_vitri = 0
_fullShikigamiCount = 0
_isPaused = False
_isFullTeam = False
_detectExitThread = threading.Thread()
_accountLocker = threading.Lock()
_replaceShikigamiIfFull = True

class Processing(threading.Thread):

    def __init__(self, windowName, total, isCaptain=False, isMainDMG=True, phoban=str("28"), vitri=int("0"), client=1, accuracy=0.9, refresh=False):
        global _accountCount
        global _accountLocker
        global _detectExitThread
        threading.Thread.__init__(self)
        self._Processing__hwnd = win32gui.FindWindow(0, windowName)
        self._Processing__total = total
        self._Processing__phoban = phoban
        self._Processing__vitri = vitri
        self._Processing__isCaptain = isCaptain
        self._Processing__isMainDMG = isMainDMG
        self.refresh_checked = refresh
        self._Processing__id = _accountCount
        self._Processing__client = client
        self.accuracy = accuracy
        self._Processing__gui = GameControl(self._Processing__hwnd, 0, self._Processing__client)
        self._Processing__thread = ThreadGame()
        self._Processing__delay = 0.5
        self._Processing__debug = False
        _accountCount += 1
        _accountLocker.acquire()
        if not _detectExitThread.is_alive():
            _detectAssistantThread = threading.Thread(None, self.detectAssistance)
            _detectAssistantThread.setDaemon(True)
            _detectAssistantThread.start()
            if self._Processing__debug == True:
                _debugTread = threading.Thread(None, self._Processing__gui.debug())
                _debugTread.setDaemon(True)
                _debugTread.start()
        _accountLocker.release()

    @property
    def accountCount(self):
        return _accountCount

    def phoban(self):
        return _phoban

    def vitri(self):
        return _vitri

    def gameModeRealmRaid(self):
        # ===== DEEP DIAGNOSTIC: log window state once at startup =====
        try:
            import hashlib, win32gui as _w
            hwnd = self._Processing__hwnd
            wr = _w.GetWindowRect(hwnd)
            cr = _w.GetClientRect(hwnd)
            cls = _w.GetClassName(hwnd)
            title = _w.GetWindowText(hwnd)
            fg = _w.GetForegroundWindow()
            is_min = _w.IsIconic(hwnd)
            children = []
            def _enum(h, _):
                children.append((h, _w.GetClassName(h)))
            _w.EnumChildWindows(hwnd, _enum, None)
            printWithTime("DIAG: hwnd=0x%08x cls=%r title=%r" % (hwnd, cls, title))
            printWithTime("DIAG: window_rect=%s client_rect=%s" % (wr, cr))
            printWithTime("DIAG: is_minimized=%s foreground_hwnd=0x%08x (same=%s)" % (is_min, fg, fg == hwnd))
            printWithTime("DIAG: child_windows=%d %s" % (len(children), children[:6]))
            printWithTime("DIAG: gui._client=%dx%d border=(%d,%d)" % (
                self._Processing__gui._client_w, self._Processing__gui._client_h,
                self._Processing__gui._border_l, self._Processing__gui._border_t))
        except Exception as _e:
            printWithTime("DIAG: setup err: %s" % _e)
        self._diag_dump_count = 0
        self._raid_done = 0
        self._section_stuck_count = 0
        self.refresh = False
        if self._Processing__vitri == 1:
            TARGET = (87, 394)
        elif self._Processing__vitri == 2:
            TARGET = (320, 355)
        elif self._Processing__vitri == 3:
            TARGET = (532, 336)
        elif self._Processing__vitri == 4:
            TARGET = (729, 339)
        elif self._Processing__vitri == 5:
            TARGET = (904, 424)
        elif self._Processing__vitri == 0:
            TARGET = (1, 1)
        printWithTime("Message: Account %s: Che do pkg, vui long cai dat team tu truoc...." % str(self._Processing__id))
        _iter = 0
        while 1:
            _iter += 1
            if _iter % 20 == 1:
                printWithTime("[LOOP] iter=%d stuck=%d done=%d refresh=%s" % (_iter, self._section_stuck_count, self._raid_done, self.refresh))
            if self.refresh_checked == True and self.refresh == True:
                position = self._Processing__gui.find_game_img(IMAGE_REALM_REFRESH_PATH, thread=(self.accuracy))
                if position != False:
                    self._Processing__gui.mouse_click_bg(position)
                    time.sleep(2)
                    self.refresh = False
                    continue
                else:
                    self.refresh = False
            if self._Processing__gui.find_game_img(IMAGE_REALM_EMPTY_TICKET, pos1=(930, 0), pos2=(1102, 38), thread=0.97) != False:
                printWithTime("Message: Account %s: DONE... " % str(self._Processing__id))
                pyautogui.alert(text="PKG Thanh cong", title="FINISH", button="OK")
                sys.exit()
            if self._Processing__gui.find_game_img(IMAGE_REALM_COOLDOWN_PATH, thread=0.85) != False:
                printWithTime("Message: Account %s: Doi tuong dang cooldown, dong popup tim doi tuong khac..." % str(self._Processing__id))
                self._Processing__gui.mouse_click_bg(COOLDOWN_DISMISS_POSITION)
                time.sleep(1)
                continue
            position = self._Processing__gui.find_game_img(IMAGE_REALM_FINISHED2_PATH, thread=(self.accuracy))
            if position != False:
                self._section_stuck_count = 0
                self._raid_done += 1
                printWithTime("Message: Account %s: Dang nhan thuong... (Da hoan thanh: %d tran)" % (str(self._Processing__id), self._raid_done))
                self._Processing__gui.mouse_click_bg(position)
                time.sleep(0.5)
                self._Processing__gui.mouse_click_bg(position)
                continue
            position = self._Processing__gui.find_game_img(IMAGE_CLICK_PATH, thread=(self.accuracy))
            click_target = position
            if position == False:
                tap_pos = self._Processing__gui.find_game_img(IMAGE_TAP_PATH, thread=(self.accuracy))
                if tap_pos != False:
                    position = tap_pos
                    click_target = TAP_READY_BUTTON
            if position != False:
                printWithTime("Dang san sang")
                time.sleep(3)
                self._Processing__gui.mouse_click_bg(click_target)
                time.sleep(3)
                self._Processing__gui.mouse_click_bg(TARGET)
                continue
            position = self._Processing__gui.find_game_img(IMAGE_REALM_BATTLE_PATH, thread=(self.accuracy))
            if position != False:
                self._section_stuck_count = 0
                printWithTime("Message: Account %s: Dang trong tran ..." % str(self._Processing__id))
                time.sleep(5)
                continue
            position = self._Processing__gui.find_game_img(IMAGE_REALM_START_PATH, thread=(self.accuracy))
            if position != False:
                self._section_stuck_count += 1
                if self._section_stuck_count >= 10:
                    printWithTime("Message: Account %s: Stuck START %d lan, dong popup tim doi tuong khac..." % (str(self._Processing__id), self._section_stuck_count))
                    self._Processing__gui.mouse_click_bg(COOLDOWN_DISMISS_POSITION)
                    time.sleep(1)
                    self._section_stuck_count = 0
                    continue
                printWithTime("Message: Account %s: [START] click at %s (stuck=%d)" % (str(self._Processing__id), position, self._section_stuck_count))
                self._Processing__gui.mouse_click_bg(position)
                continue
            position = self._Processing__gui.find_game_img(IMAGE_REALM_RAID_PATH)
            if position != False:
                printWithTime("Message: Account %s: Vui long vao giao dien pkg..." % str(self._Processing__id))
                self._Processing__gui.mouse_click_bg(position)
                continue
            position = self._Processing__gui.find_game_img(IMAGE_REALM_SECTION_PATH, thread=(self.accuracy))
            if position != False:
                self._section_stuck_count += 1
                if self._section_stuck_count >= 10:
                    printWithTime("Message: Account %s: Stuck SECTION %d lan, dong popup tim doi tuong khac..." % (str(self._Processing__id), self._section_stuck_count))
                    self._Processing__gui.mouse_click_bg(COOLDOWN_DISMISS_POSITION)
                    time.sleep(1)
                    self._section_stuck_count = 0
                    continue
                printWithTime("Message: Account %s: Tim thay ke dich (SECTION) at %s..." % (str(self._Processing__id), position))
                # ===== Dump screenshot BEFORE click =====
                if self._diag_dump_count < 3:
                    try:
                        import hashlib, win32gui as _w
                        before_path = "decompiled/dbg_%d_before.png" % self._diag_dump_count
                        self._Processing__gui.window_full_shot(file_name=before_path)
                        with open(before_path, "rb") as _f:
                            h_before = hashlib.md5(_f.read()).hexdigest()[:12]
                        # screen coords for the click we are about to send
                        scr = _w.ClientToScreen(self._Processing__hwnd, (position[0], position[1]))
                        target_dbg = self._Processing__hwnd
                        try:
                            child = _w.ChildWindowFromPoint(self._Processing__hwnd, (position[0], position[1]))
                            if child and child != self._Processing__hwnd:
                                target_dbg = child
                        except Exception:
                            pass
                        printWithTime("DIAG#%d: SECTION client=%s screen=%s target_hwnd=0x%08x hash=%s" % (
                            self._diag_dump_count, position, scr, target_dbg, h_before))
                    except Exception as _e:
                        printWithTime("DIAG dump-before err: %s" % _e)
                self._Processing__gui.mouse_click_bg(position)
                time.sleep(1)
                # ===== Dump screenshot AFTER click =====
                if self._diag_dump_count < 3:
                    try:
                        import hashlib
                        after_path = "decompiled/dbg_%d_after.png" % self._diag_dump_count
                        self._Processing__gui.window_full_shot(file_name=after_path)
                        with open(after_path, "rb") as _f:
                            h_after = hashlib.md5(_f.read()).hexdigest()[:12]
                        printWithTime("DIAG#%d: AFTER click hash=%s (changed=%s)" % (
                            self._diag_dump_count, h_after, h_after != h_before))
                    except Exception as _e:
                        printWithTime("DIAG dump-after err: %s" % _e)
                    self._diag_dump_count += 1
                _maxVal, _maxLoc = self._Processing__gui.find_img(IMAGE_REALM_START_PATH, gray=1)
                printWithTime("DBG: Attack score=%.3f at %s -> clicking anyway" % (_maxVal, _maxLoc))
                if isinstance(_maxLoc, list) and len(_maxLoc) == 2:
                    self._Processing__gui.mouse_click_bg(_maxLoc)
                    printWithTime("Message: Account %s: >>> Da nhan ATTACK at %s (stuck=%d)" % (str(self._Processing__id), _maxLoc, self._section_stuck_count))
                continue
            self._section_stuck_count = 0
            position = self._Processing__gui.find_game_img(IMAGE_REALM_FROG_PATH, thread=(self.accuracy))
            if position != False:
                printWithTime("Message: Account %s: Tim thay ke dich (FROG) at %s..." % (str(self._Processing__id), position))
                self._Processing__gui.mouse_click_bg(position)
                time.sleep(0.5)
                _maxVal, _maxLoc = self._Processing__gui.find_img(IMAGE_REALM_START_PATH, gray=1)
                printWithTime("DBG: Attack score=%.3f at %s -> clicking anyway" % (_maxVal, _maxLoc))
                if isinstance(_maxLoc, list) and len(_maxLoc) == 2:
                    self._Processing__gui.mouse_click_bg(_maxLoc)
                    printWithTime("Message: Account %s: >>> Da nhan ATTACK at %s (stuck=%d)" % (str(self._Processing__id), _maxLoc, self._section_stuck_count))
                continue
            position = self._Processing__gui.find_game_img(IMAGE_REALM_FINISHED1_PATH, gray=0, thread=(self.accuracy))
            if position != False:
                printWithTime("Message: Account %s: Dang ket thuc..." % str(self._Processing__id))
                self._Processing__gui.mouse_click_bg(position)
                continue
            position = self._Processing__gui.find_game_img(IMAGE_REALM_FAILED_PATH, gray=0, thread=(self.accuracy))
            if position != False:
                printWithTime("Message: Account %s: Dich manh qua =))... " % str(self._Processing__id))
                self._Processing__gui.mouse_click_bg(position)
                self.refresh = True
                continue
            if self._Processing__gui.find_game_img(IMAGE_REALM_SECTION_PATH, thread=(self.accuracy)) == False:
                if self._Processing__gui.find_game_img(IMAGE_REALM_RANK_PATH, thread=(self.accuracy)) != False:
                    printWithTime("Message: Account %s: Dang lam moi... " % str(self._Processing__id))
                    position = self._Processing__gui.find_game_img(IMAGE_REALM_REFRESH_PATH, thread=(self.accuracy))
                    if position != False:
                        self._Processing__gui.mouse_click_bg(position)
                        time.sleep(2)
            position = self._Processing__gui.find_game_img(IMAGE_REALM_OK_PATH, thread=(self.accuracy))
            if position != False:
                self._Processing__gui.mouse_click_bg(position)
                continue

    def detectPause(self):
        global _isPaused
        while True:
            keyboard.wait(hotkey="f1")
            printWithTime("Message: F1 was pressed")
            if _isPaused:
                _isPaused = False
                _accountLocker.release()
                printWithTime("Continued")
            else:
                _isPaused = True
                _accountLocker.acquire()
                printWithTime("Paused")

    def detectAssistance(self):
        # Disabled: coop-seal detection khong can cho Pha ket gioi
        return

    def targetShikigami(self, location=None):
        while 1:
            printWithTime("Đang targrt")
            profile = self._Processing__gui.find_game_img(IMAGE_REALM_PROFILE_PATH, thread=0.8)
            set = self._Processing__gui.find_game_img(IMAGE_SOUL_SET_PATH, thread=0.8)
            if profile != False:
                if set == False:
                    profile = self._Processing__gui.find_game_img(IMAGE_REALM_PROFILE_PATH, thread=0.8)
                    target = self._Processing__gui.find_game_img(IMAGE_EVENT_TARGET, thread=0.8)
                    if target == False:
                        if profile != False:
                            message = "Message: Account %s: Target to the 5th shikigami..." % str(self._Processing__id)
                            printWithTime(message)
                            self._Processing__gui.mouse_click_bg((859, 423))
                            time.sleep(1)
                        if target != False:
                            if profile != False:
                                while self.isInBattle():
                                    printWithTime("Message: Account %s: In battle detected, sleep 5s ..." % str(self._Processing__id))
                                    time.sleep(5)

                                break
                    time.sleep(1)

    def run(self):
        _localVariable.isBossDetected = False
        _localVariable.isInBattle = False
        _localVariable.isInRoom = False
        _localVariable.detectCount = 10
        _localVariable.slide = 3
        count = 0
        while self._Processing__total - count > 0:
            seconds = 0
            while seconds:
                time.sleep(1)
                seconds -= 1

            printWithTime("\n\n==============Account %s: " % str(self._Processing__id) + "Starting a new round==================")
            _localVariable.detectCount = 10
            _localVariable.xDirection = -1.0
            self.gameModeRealmRaid()
            count += 1
