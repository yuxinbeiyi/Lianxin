import json
from pathlib import Path
from PyQt5.QtCore import QObject, QTimer, pyqtSignal, Qt
from PyQt5.QtGui import QMovie, QPixmap
from PyQt5.QtWidgets import QLabel


class AnimationStateMachine(QObject):
    """管理角色动画状态机"""
    state_changed = pyqtSignal(str)

    def __init__(self, label: QLabel, config_path: str, assets_dir: str, parent=None,
                 skip_initial: bool = False):
        super().__init__(parent)
        self.label = label
        self.config_path = Path(config_path)
        self.assets_dir = Path(assets_dir)
        self.config = self._load_config()
        self.current_mode = "normal"
        self.current_state = None
        self.current_movie = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_timer)
        self._pending_event = None
        self._movie_cache = {}
        self._current_anim_file = ""  # 当前 label 上显示的动画文件路径
        if not skip_initial:
            # 只创建首个状态的 QMovie。旧实现会把所有模式的全部 GIF
            # 一次性 CacheAll，启动时会触发大量解码和内存分配，导致
            # Qt 主界面短暂白屏、鼠标事件堆积。
            self._goto_state(self.config["modes"][self.current_mode]["initial"])

    def _load_config(self):
        if not self.config_path.exists():
            raise FileNotFoundError(f"动画配置文件不存在: {self.config_path}")
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _preload_all_movies(self):
        """兼容旧调用名：仅加载当前初始状态，不再预加载全部 GIF。"""
        initial = self.config["modes"][self.current_mode]["initial"]
        self._ensure_movie(self.current_mode, initial)

    def _ensure_movie(self, mode_name, state_name):
        cache_key = (mode_name, state_name)
        if cache_key in self._movie_cache:
            return self._movie_cache[cache_key]
        try:
            anim_file = self.config["modes"][mode_name]["states"][state_name]["animation"]
        except KeyError:
            return None
        full_path = self.assets_dir / anim_file
        if not full_path.exists():
            print(f"警告: 动画文件不存在 {full_path}")
            return None
        movie = QMovie(str(full_path))
        # 当前动画按帧解码，避免一次性把数十个 GIF 的全部帧压入内存。
        movie.setCacheMode(QMovie.CacheNone)
        self._movie_cache[cache_key] = movie
        return movie


    def set_mode(self, mode: str):
        if mode not in self.config["modes"]:
            print(f"未知模式: {mode}")
            return
        self.current_mode = mode
        self._goto_state(self.config["modes"][mode]["initial"])

    def trigger_event(self, event: str):
        if self.current_state is None:
            return
        state_def = self.config["modes"][self.current_mode]["states"].get(self.current_state)
        if state_def and "on_event" in state_def and event in state_def["on_event"]:
            if "duration" in state_def:
                self._pending_event = event
            else:
                self._goto_state(state_def["on_event"][event])

    def _goto_state(self, state_name: str):
        if self.current_state == state_name:
            return  # 已在目标状态，跳过
        self.timer.stop()
        # 检查状态是否存在
        try:
            state_def = self.config["modes"][self.current_mode]["states"][state_name]
        except KeyError:
            print(f"错误: 状态 '{state_name}' 不存在于模式 '{self.current_mode}' 中")
            print(f"可用状态: {list(self.config['modes'][self.current_mode]['states'].keys())}")
            return
        cache_key = (self.current_mode, state_name)
        new_movie = self._ensure_movie(self.current_mode, state_name)
        if new_movie is None:
            print(f"错误: 无法加载动画 {self.current_mode}/{state_name}")
            return
        self.current_state = state_name
        anim_file = state_def["animation"]
        print(f"[动画] 模式: {self.current_mode}, 状态: {state_name}, 文件: {anim_file}")

        # 避免重复 setMovie：如果 label 上已是同一文件，只重启动画
        if anim_file == self._current_anim_file and self.current_movie:
            self.current_movie.stop()
            QTimer.singleShot(0, self.current_movie.start)
        else:
            if self.current_movie:
                self.current_movie.stop()
            self.current_movie = new_movie
            self._current_anim_file = anim_file
            self.label.setMovie(self.current_movie)
            movie_ref = self.current_movie
            QTimer.singleShot(0, movie_ref.start)


        self.state_changed.emit(state_name)
        if "duration" in state_def:
            self.timer.start(int(state_def["duration"] * 1000))
        elif "next" in state_def:
            self.timer.start(0)

    def _on_timer(self):
        if self.current_state is None:
            return
        try:
            state_def = self.config["modes"][self.current_mode]["states"][self.current_state]
        except KeyError:
            print(f"错误: 当前状态 '{self.current_state}' 在模式 '{self.current_mode}' 中不存在")
            return
        if self._pending_event:
            event = self._pending_event
            self._pending_event = None
            if "on_event" in state_def and event in state_def["on_event"]:
                self._goto_state(state_def["on_event"][event])
                return
        if "next" in state_def:
            self._goto_state(state_def["next"])

    def set_static_pixmap(self, pixmap):
        self.timer.stop()
        if self.current_movie:
            self.current_movie.stop()
            self.current_movie = None
        self._current_anim_file = ""
        self.label.setMovie(QMovie())
        self.label.setPixmap(pixmap)

    def restore_animation(self):
        self._goto_state(self.config["modes"][self.current_mode]["initial"])
