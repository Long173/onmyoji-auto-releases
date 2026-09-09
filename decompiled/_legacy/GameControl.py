# uncompyle6 version 3.9.3
# Python bytecode version base 3.6 (3379)
# Decompiled from: Python 3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
# Embedded file name: GameControl.py
# Compiled at: 2021-09-22 16:15:28
# Size of source mod 2**32: 30688 bytes
import ctypes, logging, os, sys, time, traceback, random, cv2, numpy as np, win32api, win32con, win32gui, win32ui
from timeit import default_timer as timer
from PIL import Image

class GameControl:

    def __init__(self, hwnd, quit_game_enable=1, client=0):
        """
        initialization

            : param hwnd: the window handle to be bound

            : param quit_game_enable: Whether to exit the game when the program dies. 
            True is yes, False is no
        """
        self.run = True
        self.hwnd = hwnd
        print(client)
        self.client = client
        self.quit_game_enable = quit_game_enable
        self.debug_enable = False
        l1, t1, r1, b1 = win32gui.GetWindowRect(self.hwnd)
        l2, t2, r2, b2 = win32gui.GetClientRect(self.hwnd)
        self._client_h = b2 - t2
        self._client_w = r2 - l2
        self._border_l = (r1 - l1 - (r2 - l2)) // 2
        self._border_t = b1 - t1 - (b2 - t2) - self._border_l
        if self.client == 1:
            os.system("adb kill-server")
            os.system("adb connect 127.0.0.1:7555")
            os.system("adb devices")

    def init_mem(self):
        self.hwindc = win32gui.GetWindowDC(self.hwnd)
        self.srcdc = win32ui.CreateDCFromHandle(self.hwindc)
        self.memdc = self.srcdc.CreateCompatibleDC()
        self.bmp = win32ui.CreateBitmap()
        self.bmp.CreateCompatibleBitmap(self.srcdc, self._client_w, self._client_h)
        self.memdc.SelectObject(self.bmp)
        l1, t1, r1, b1 = win32gui.GetWindowRect(self.hwnd)
        self._win_w = max(1, r1 - l1)
        self._win_h = max(1, b1 - t1)
        self.win_memdc = self.srcdc.CreateCompatibleDC()
        self.win_bmp = win32ui.CreateBitmap()
        self.win_bmp.CreateCompatibleBitmap(self.srcdc, self._win_w, self._win_h)
        self.win_memdc.SelectObject(self.win_bmp)
        self._printwindow_warned = False

    def _capture_via_printwindow(self):
        # PW_RENDERFULLCONTENT = 0x2 forces DirectX/DWM-rendered content (Unity, etc.)
        # to be drawn into the supplied DC. BitBlt(GetWindowDC) cannot do this on
        # DX-backed surfaces and returns a stale GDI snapshot.
        try:
            ok = ctypes.windll.user32.PrintWindow(self.hwnd, self.win_memdc.GetSafeHdc(), 2)
            if ok != 1:
                if not self._printwindow_warned:
                    print("[CAPTURE] PrintWindow FAILED (rc={}); switching to BitBlt fallback".format(ok), flush=True)
                    self._printwindow_warned = True
                    self._printwindow_ok_logged = False  # let next success log "back active"
                return False
            if not getattr(self, "_printwindow_ok_logged", False):
                print("[CAPTURE] PrintWindow(PW_RENDERFULLCONTENT) ACTIVE for hwnd=0x{:08x}".format(self.hwnd), flush=True)
                self._printwindow_ok_logged = True
                self._printwindow_warned = False  # let next failure log again
            return True
        except Exception:
            if not self._printwindow_warned:
                print("[CAPTURE] PrintWindow raised; falling back to BitBlt\n{}".format(traceback.format_exc()), flush=True)
                self._printwindow_warned = True
                self._printwindow_ok_logged = False
            return False

    def window_full_shot(self, file_name=None, gray=0):
        """
       Window screenshot

            : param file_name = None: save name of screenshot file

            : param gray = 0: whether to return grayscale image, 0: return BGR color image, others: return grayscale black and white image

            : return: return RGB data if file_name is empty
        """
        try:
            if not hasattr(self, "memdc"):
                self.init_mem()
            if self.client == 0 and self._capture_via_printwindow():
                self.memdc.BitBlt((0, 0), (self._client_w, self._client_h), self.win_memdc, (
                 self._border_l, self._border_t), win32con.SRCCOPY)
            elif self.client == 0:
                self.memdc.BitBlt((0, 0), (self._client_w, self._client_h), self.srcdc, (
                 self._border_l, self._border_t), win32con.SRCCOPY)
            else:
                self.memdc.BitBlt((0, -35), (self._client_w, self._client_h), self.srcdc, (
                 self._border_l, self._border_t), win32con.SRCCOPY)
            if file_name != None:
                self.bmp.SaveBitmapFile(self.memdc, file_name)
                return
            else:
                signedIntsArray = self.bmp.GetBitmapBits(True)
                img = np.frombuffer(signedIntsArray, dtype="uint8")
                img.shape = (self._client_h, self._client_w, 4)
                if gray == 0:
                    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        except Exception:
            self.init_mem()

    def window_part_shot(self, pos1, pos2, file_name=None, gray=0):
        """
        Screenshot of the window area

            : param pos1: (x, y) coordinates of the upper left corner of the screenshot area

            : param pos2: (x, y) coordinates of the lower right corner of the screenshot area

            : param file_name = None: save path of screenshot file

            : param gray = 0: whether to return grayscale image, 0: return BGR color image, others: return grayscale black and white image

            : return: return RGB data if file_name is empty
        """
        w = pos2[0] - pos1[0]
        h = pos2[1] - pos1[1]
        if not hasattr(self, "win_memdc"):
            self.init_mem()
        used_pw = self.client == 0 and self._capture_via_printwindow()
        hwindc = win32gui.GetWindowDC(self.hwnd)
        srcdc = win32ui.CreateDCFromHandle(hwindc)
        memdc = srcdc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(srcdc, w, h)
        memdc.SelectObject(bmp)
        if used_pw:
            memdc.BitBlt((0, 0), (w, h), self.win_memdc, (
             pos1[0] + self._border_l, pos1[1] + self._border_t), win32con.SRCCOPY)
        elif self.client == 0:
            memdc.BitBlt((0, 0), (w, h), srcdc, (
             pos1[0] + self._border_l, pos1[1] + self._border_t), win32con.SRCCOPY)
        else:
            memdc.BitBlt((0, -35), (w, h), srcdc, (
             pos1[0] + self._border_l, pos1[1] + self._border_t), win32con.SRCCOPY)
        if file_name != None:
            bmp.SaveBitmapFile(memdc, file_name)
            srcdc.DeleteDC()
            memdc.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwindc)
            win32gui.DeleteObject(bmp.GetHandle())
            return
        else:
            signedIntsArray = bmp.GetBitmapBits(True)
            img = np.frombuffer(signedIntsArray, dtype="uint8")
            img.shape = (h, w, 4)
            srcdc.DeleteDC()
            memdc.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwindc)
            win32gui.DeleteObject(bmp.GetHandle())
            if gray == 0:
                return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)

    def find_color(self, region, color, tolerance=0):
        """
        Looking for color

            : param region: ((x1, y1), (x2, y2)) coordinates of the upper left corner and lower right corner of the area to be searched

            : param color: (r, g, b) The color to search

            : param tolerance = 0: tolerance value

            : return: successfully returns the coordinates of the client area, -1 if it fails
        """
        img = Image.fromarray(self.window_part_shot(region[0], region[1]), "RGB")
        width, height = img.size
        r1, g1, b1 = color[:3]
        for x in range(width):
            for y in range(height):
                try:
                    pixel = img.getpixel((x, y))
                    r2, g2, b2 = pixel[:3]
                    if abs(r1 - r2) <= tolerance:
                        if abs(g1 - g2) <= tolerance:
                            if abs(b1 - b2) <= tolerance:
                                return (
                                 x + region[0][0], y + region[0][1])
                except Exception:
                    logging.warning("find_color failed to execute")
                    a = traceback.format_exc()
                    logging.warning(a)
                    return -1

        return -1

    def check_color(self, pos, color, tolerance=0):
        """
        Compare the color of a point in the window

            : param pos: (x, y) the coordinates to compare

            : param color: (r, g, b) the color to be compared

            : param tolerance = 0: tolerance value

            : return: returns True on success, False on failure
        """
        img = Image.fromarray(self.window_full_shot(), "RGB")
        r1, g1, b1 = color[:3]
        r2, g2, b2 = img.getpixel(pos)[:3]
        if abs(r1 - r2) <= tolerance:
            if abs(g1 - g2) <= tolerance:
                if abs(b1 - b2) <= tolerance:
                    return True
        return False

    def find_img(self, img_template_path, part=0, pos1=None, pos2=None, gray=0, center=True, delay=0.1):
        """
        Find pictures

            : param img_template_path: the path of the image to be found

            : param part = 0: whether to search in full screen, 1 is no, other is yes

            : param pos1 = None: the coordinates of the upper left corner of the range to be searched

            : param pos2 = None: the coordinates of the lower right corner of the range to be searched

            : param gray = 0: whether to search by color, 0: find color pictures, 1: find black and white pictures

            : return: (maxVal, maxLoc) maxVal is the correlation, the closer to 1, the better, maxLoc is the obtained coordinate
        """
        time.sleep(delay)
        if part == 1:
            img_src = self.window_part_shot(pos1, pos2, None, gray)
        else:
            img_src = self.window_full_shot(None, gray)
        if gray == 0:
            img_template = cv2.imread(img_template_path, cv2.IMREAD_COLOR)
        else:
            img_template = cv2.imread(img_template_path, cv2.IMREAD_GRAYSCALE)
        try:
            res = cv2.matchTemplate(img_src, img_template, cv2.TM_CCOEFF_NORMED)
            minVal, maxVal, minLoc, maxLoc = cv2.minMaxLoc(res)
            if self.debug_enable:
                if part == 1:
                    img = self.window_part_shot(pos1, pos2, None, gray)
                else:
                    img = self.window_full_shot()
                self.img = cv2.rectangle(img, maxLoc, (maxLoc[0] + img_template.shape[1], maxLoc[1] + img_template.shape[0]), (0,
                                                                                                                               255,
                                                                                                                               0), 3)
                show_img(img)
                print("Top left point location: ", maxLoc)
                print("Score: ", maxVal)
            if center:
                maxLoc = list(maxLoc)
                maxLoc[0] = int(maxLoc[0] + img_template.shape[1] / 2)
                maxLoc[1] = int(maxLoc[1] + img_template.shape[0] / 2)
            return (
             maxVal, maxLoc)
        except Exception:
            return (1, 1)

    def find_img_knn(self, img_template_path, part=0, pos1=None, pos2=None, gray=0, thread=0, center=True):
        """
        Find pictures, knn algorithm
        param img_template_path: the path of the image to be found
        param part = 0: whether to search in full screen, 1 is no, other is yes
        param pos1 = None: the coordinates of the upper left corner of the range to be searched
        param pos2 = None: the coordinates of the lower right corner of the range to be searched
        param gray = 0: whether to search by color, 0: find color pictures, 1: find black and white pictures
        return: coordinates (x, y), return (0, 0) if not found, -1 if it fails
        """
        if part == 1:
            img_src = self.window_part_shot(pos1, pos2, None, gray)
        else:
            img_src = self.window_full_shot(None, gray)
        if gray == 0:
            img_template = cv2.imread(img_template_path, cv2.IMREAD_COLOR)
        else:
            img_template = cv2.imread(img_template_path, cv2.IMREAD_GRAYSCALE)
        try:
            maxLoc = match_img_knn(img_template, img_src, thread)
            if self.debug_enable:
                if part == 1:
                    img = self.window_part_shot(pos1, pos2, None, gray)
                else:
                    img = self.window_full_shot()
                self.img = cv2.rectangle(img, maxLoc, (maxLoc[0] + img_template.shape[1], maxLoc[1] + img_template.shape[0]), (0,
                                                                                                                               255,
                                                                                                                               0), 3)
                print("Top left point location: ", maxLoc)
                show_img(img)
            if center:
                maxLoc = list(maxLoc)
                maxLoc[0] = int(maxLoc[0] + img_template.shape[1] / 2)
                maxLoc[1] = int(maxLoc[1] + img_template.shape[0] / 2)
                maxLoc = tuple(maxLoc)
            return maxLoc
        except Exception:
            logging.warning("find_img_knn failed to execute")
            a = traceback.format_exc()
            logging.warning(a)
            return -1

    def find_multi_img(self, *img_template_path, part=0, pos1=None, pos2=None, gray=0):
        """
        Find multiple pictures
        : param img_template_path: list of image paths to find
        : param part = 0: whether to search in full screen, 1 is no, other is yes
        : param pos1 = None: the coordinates of the upper left corner of the range to be searched
        : param pos2 = None: the coordinates of the lower right corner of the range to be searched
        : param gray = 0: whether to search by colo:r, 0: find color pictures, 1: find black and white pictures
        : return: (maxVal, maxLoc) maxVal is the correlation list, the closer to 1, the better, maxLoc is the obtained coordinate list
        """
        if part == 1:
            img_src = self.window_part_shot(pos1, pos2, None, gray)
        else:
            img_src = self.window_full_shot(None, gray)
        maxVal_list = []
        maxLoc_list = []
        for item in img_template_path:
            if gray == 0:
                img_template = cv2.imread(item, cv2.IMREAD_COLOR)
            else:
                img_template = cv2.imread(item, cv2.IMREAD_GRAYSCALE)
            try:
                res = cv2.matchTemplate(img_src, img_template, cv2.TM_CCOEFF_NORMED)
                minVal, maxVal, minLoc, maxLoc = cv2.minMaxLoc(res)
                maxVal_list.append(maxVal)
                maxLoc_list.append(maxLoc)
            except Exception:
                logging.warning("find_multi_img执行失败")
                a = traceback.format_exc()
                logging.warning(a)
                maxVal_list.append(0)
                maxLoc_list.append(0)

        return (
         maxVal_list, maxLoc_list)

    def activate_window(self):
        user32 = ctypes.WinDLL("user32.dll")
        user32.SwitchToThisWindow(self.hwnd, True)

    def mouse_move(self, pos, pos_end=None):
        """
        Simulate mouse movement
        : param pos: (x, y) the coordinates of the mouse movement
        : param pos_end = None: (x, y) If pos_end is not empty, 
        the mouse moves to a random position in the area where pos is the upper left corner coordinate pos_end is the lower right corner coordinate
        """
        pos2 = win32gui.ClientToScreen(self.hwnd, pos)
        if pos_end == None:
            win32api.SetCursorPos(pos2)
        else:
            pos_end2 = win32gui.ClientToScreen(self.hwnd, pos_end)
            pos_rand = (
             random.randint(pos2[0], pos_end2[0]), random.randint(pos2[1], pos_end2[1]))
            win32api.SetCursorPos(pos_rand)

    def mouse_click(self):
        """
        Mouse click
        """
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(random.randint(20, 80) / 1000)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def mouse_drag(self, pos1, pos2):
        """
        Mouse drag
        : param pos1: (x, y) starting point coordinates
        : param pos2: (x, y) end point coordinates
        """
        pos1_s = win32gui.ClientToScreen(self.hwnd, pos1)
        pos2_s = win32gui.ClientToScreen(self.hwnd, pos2)
        screen_x = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_y = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        start_x = pos1_s[0] * 65535 // screen_x
        start_y = pos1_s[1] * 65535 // screen_y
        dst_x = pos2_s[0] * 65535 // screen_x
        dst_y = pos2_s[1] * 65535 // screen_y
        move_x = np.linspace(start_x, dst_x, num=20, endpoint=True)[0:]
        move_y = np.linspace(start_y, dst_y, num=20, endpoint=True)[0:]
        self.mouse_move(pos1)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        for i in range(20):
            x = int(round(move_x[i]))
            y = int(round(move_y[i]))
            win32api.mouse_event(win32con.MOUSEEVENTF_MOVE | win32con.MOUSEEVENTF_ABSOLUTE, x, y, 0, 0)
            time.sleep(0.01)

        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def mouse_click_bg(self, pos, pos_end=None):
        if pos_end is None:
            pos_rand = pos
        else:
            pos_rand = (random.randint(pos[0], pos_end[0]), random.randint(pos[1], pos_end[1]))
        print("[CLICK] %s" % (pos_rand,), flush=True)
        if self.debug_enable:
            img = self.window_full_shot()
            self.img = cv2.rectangle(img, pos, None, (255, 0, 0), 3)
            show_img(img)
        if self.client == 0:
            lp = win32api.MAKELONG(pos_rand[0], pos_rand[1])
            target = self.hwnd
            try:
                child = win32gui.ChildWindowFromPoint(self.hwnd, (pos_rand[0], pos_rand[1]))
                if child and child != self.hwnd:
                    target = child
            except Exception:
                pass
            win32gui.PostMessage(target, win32con.WM_MOUSEMOVE, 0, lp)
            time.sleep(0.01)
            win32gui.PostMessage(target, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
            time.sleep(random.randint(40, 100) / 1000)
            win32gui.PostMessage(target, win32con.WM_LBUTTONUP, 0, lp)
        else:
            command = str(pos_rand[0]) + " " + str(pos_rand[1])
            os.system("adb shell input tap " + command)

    def mouse_drag_bg(self, pos1, pos2, delay=0.02):
        """
            :param pos1: (x,y) 
            :param pos2: (x,y) 
        """
        if self.client == 0:
            move_x = np.linspace((pos1[0]), (pos2[0]), num=20, endpoint=True)[0:]
            move_y = np.linspace((pos1[1]), (pos2[1]), num=20, endpoint=True)[0:]
            win32gui.SendMessage(self.hwnd, win32con.WM_LBUTTONDOWN, 0, win32api.MAKELONG(pos1[0], pos1[1]))
            for i in range(20):
                x = int(round(move_x[i]))
                y = int(round(move_y[i]))
                win32gui.SendMessage(self.hwnd, win32con.WM_MOUSEMOVE, 0, win32api.MAKELONG(x, y))
                time.sleep(delay)

            win32gui.SendMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, win32api.MAKELONG(pos2[0], pos2[1]))
        else:
            command = str(pos1[0]) + " " + str(pos1[1]) + " " + str(pos2[0]) + " " + str(pos2[1])
            os.system("adb shell input swipe " + command)

    def wait_game_img(self, img_path, max_time=100, quit=True):
        """
        Waiting for game image
        : param img_path: image path
        : param max_time = 60: timeout time
        : param quit = True: whether to quit after timeout
        : return: return coordinates successfully, False if failed
        """
        self.rejectbounty()
        start_time = time.time()
        while time.time() - start_time <= max_time:
            if self.run:
                maxVal, maxLoc = self.find_img(img_path)
                if maxVal > 0.9:
                    return maxLoc
                if max_time > 5:
                    time.sleep(1)
            else:
                time.sleep(0.1)

        if quit:
            self.quit_game()
        else:
            return False

    def wait_game_img_knn(self, img_path, max_time=100, quit=True, thread=0):
        """
        Waiting for game image
        : param img_path: image path
        : param max_time = 60: timeout time
        : param quit = True: whether to quit after timeout
        : return: return coordinates successfully, False if failed
        """
        self.rejectbounty()
        start_time = time.time()
        while time.time() - start_time <= max_time:
            if self.run:
                maxLoc = self.find_img_knn(img_path, thread=thread)
                if maxLoc != (0, 0):
                    return maxLoc
                if max_time > 5:
                    time.sleep(1)
            else:
                time.sleep(0.1)

        if quit:
            self.quit_game()
        else:
            return False

    def wait_game_color(self, region, color, tolerance=0, max_time=60, quit=True):
        """
       Waiting for game color
        : param region: ((x1, y1), (x2, y2)) The region to search
        : param color: (r, g, b) the color to wait for
        : param tolerance = 0: tolerance value
        : param max_time = 30: timeout time
        : param quit = True: whether to quit after timeout
        : return: Returns True on success, False on failure
        """
        self.rejectbounty()
        start_time = time.time()
        while time.time() - start_time <= max_time and self.run:
            pos = self.find_color(region, color)
            if pos != -1:
                return True
            time.sleep(1)

        if quit:
            self.quit_game()
        else:
            return False

    def quit_game(self):
        """
        exit the game
        """
        self.clean_mem()
        sys.exit(0)

    def takescreenshot(self):
        """
        Screenshot
        """
        name = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
        img_src_path = "img/screenshots/%s.png" % name
        self.window_full_shot(img_src_path)
        logging.info("Screenshot has been saved to img/screenshots/%s.png" % name)

    def rejectbounty(self):
        """
        Refusal
        return: refuse to return True, otherwise return False
        """
        maxVal, maxLoc = self.find_img("./screenshots/coopwanted.png", thread=0.8)
        if maxVal > 0.9:
            self.mouse_click_bg((749, 453))
            return True
        else:
            return False

    def find_game_img(self, img_path, part=0, pos1=None, pos2=None, gray=1, center=True, thread=0.9):
        """
        Find pictures
        : param img_path: search path
        : param part = 0: whether to search in full screen, 0 is no, other is yes
        : param pos1 = None: the coordinates of the upper left corner of the range to be searched
        : param pos2 = None: the coordinates of the lower right corner of the range to be searched
        : param gray = 0: whether to find black and white pictures, 0: find color pictures, 1: find black and white pictures
        : param thread = 0.9: custom threshold
        : return: Returns the position coordinates after successful search, otherwise returns False
        """
        maxVal, maxLoc = self.find_img(img_path, part, pos1, pos2, gray, center)
        if maxVal > thread:
            if type(maxLoc) is not int:
                return list(maxLoc)
        return False

    def find_game_img_knn(self, img_path, part=0, pos1=None, pos2=None, gray=1, center=True, thread=0):
        """
        Find pictures
        : param img_path: search path
        : param part = 0: whether to search in full screen, 0 is no, other is yes
        : param pos1 = None: the coordinates of the upper left corner of the range to be searched
        : param pos2 = None: the coordinates of the lower right corner of the range to be searched
        : param gray = 0: whether to find black and white pictures, 0: find color pictures, 1: find black and white pictures
        : param thread = 0:
        : return: Returns the position coordinates after successful search, otherwise returns False
        """
        maxLoc = self.find_img_knn(img_path, part, pos1, pos2, gray, thread, center)
        if maxLoc != (0, 0):
            return maxLoc
        else:
            return False

    def debug(self):
        """
        Self-test resolution and click range
        """
        self.debug_enable = True
        self.img = self.window_full_shot()
        logging.info("Game resolution:" + str(self.img.shape))
        while 1:
            cv2.imshow("Click Area (Press 'q' to exit)", self.img)
            k = cv2.waitKey(1) & 255
            if k == ord("q"):
                break

        cv2.destroyAllWindows()
        self.debug_enable = False

    def clean_mem(self):
        """
        Clean up memory
        """
        self.srcdc.DeleteDC()
        self.memdc.DeleteDC()
        win32gui.ReleaseDC(self.hwnd, self.hwindc)
        win32gui.DeleteObject(self.bmp.GetHandle())


def match_img_knn(queryImage, trainingImage, thread=0):
    thread = 0
    sift = cv2.SIFT_create()
    kp1, des1 = sift.detectAndCompute(queryImage, None)
    kp2, des2 = sift.detectAndCompute(trainingImage, None)
    FLANN_INDEX_KDTREE = 1
    indexParams = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
    searchParams = dict(checks=50)
    flann = cv2.FlannBasedMatcher(indexParams, searchParams)
    matches = flann.knnMatch(des1, des2, k=2)
    good = []
    matchesMask = [[0, 0] for i in range(len(matches))]
    for i, (m, n) in enumerate(matches):
        if m.distance < 0.7 * n.distance:
            matchesMask[i] = [
             1, 0]
            good.append(m)

    s = sorted(good, key=(lambda x: x.distance))
    if len(good) > thread:
        maxLoc = kp2[s[0].trainIdx].pt
        return (
         int(maxLoc[0]), int(maxLoc[1]))
    else:
        return (0, 0)


def show_img(img):
    cv2.imshow("image", img)
    cv2.imwrite("main.png", img)
    cv2.waitKey(0)


def callback(hwnd, hwnds):
    if win32gui.IsWindowVisible(hwnd):
        if win32gui.IsWindowEnabled(hwnd):
            hwnds[win32gui.GetClassName(hwnd)] = hwnd
    return True


def main():
    hwnd = win32gui.FindWindow(0, "Onmyoji")
    yys = GameControl(hwnd, 0, 0)
    yys.activate_window()
    yys.mouse_click_bg((681, 351))
    yys.debug_enable = True
    a = yys.window_full_shot()
    cv2.rectangle(a, (0, 0), (520, 600), (0, 255, 0), 3)
    show_img(a)


if __name__ == "__main__":
    main()
