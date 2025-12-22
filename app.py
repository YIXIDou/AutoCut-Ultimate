# app.py 顶部
from test_core import find_scenes_optimized, frames_to_timecode_premiere, export_video_clips
import customtkinter as ctk
from tkinter import filedialog, messagebox
import threading
import cv2
from PIL import Image
import os
import subprocess


# 引入后端
from test_core import find_scenes_optimized, frames_to_timecode_premiere

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class AutoCutApp(ctk.CTk):
    # app.py 中的 run_analysis 方法
    def run_analysis(self):
        try:
            curr_th = round(self.slider_threshold.get(), 1)
            curr_min = int(self.slider_min_len.get())
            
            # 定义一个简单的回调函数，用于更新UI进度条
            def update_progress(p):
                self.progress_bar.set(p)

            # 【关键修改】传入 callback 和 stop_event
            scenes, fps = find_scenes_optimized(
                self.video_path, 
                curr_th, 
                curr_min,
                progress_callback=update_progress, # 传入回调
                stop_event=self.stop_event         # 传入停止标志
            )
            
            # 如果是中途停止的，stop_event 会被触发，但 scenedetect 还是会返回已识别的部分
            if self.stop_event.is_set():
                print("分析已停止 (UI层检测)")
                # 你可以选择是否显示部分结果，这里我们选择显示
            
            self.scene_list = scenes
            self.fps = fps
            self.selected_indices = set(range(len(self.scene_list)))
            self.after(0, self.update_ui_after_analysis)
                
        except Exception as e:
            print(f"Error: {e}")
            self.after(0, lambda: messagebox.showerror("错误", str(e)))
            self.after(0, lambda: self.btn_start.configure(state="normal", text="重试"))
        finally:
            self.is_analyzing = False
            # 进度条归位逻辑可以放在 update_ui_after_analysis 里，或者这里
            self.after(0, lambda: self.btn_stop.configure(state="disabled", text="⏹ 停止任务"))

    def __init__(self):
        super().__init__()

        self.title("AutoCut Ultimate - 动漫分镜切片助手 (Perfect UI)")
        self.geometry("1300x850")
        self.minsize(1000, 700)

        # --- 数据存储 ---
        self.video_path = ""
        self.scene_list = [] 
        self.selected_indices = set() 
        self.fps = 24.0
        self.cap = None 
        self.current_frame_idx = 0 
        
        self.stop_event = threading.Event()
        self.is_analyzing = False
        self.is_exporting = False
        
        self.current_page = 0
        self.items_per_page = 20

        # --- 布局配置 (关键修复点) ---
        # 1. 强制右侧列表 (Column 2) 至少有 320px 宽，防止被挤压
        self.grid_columnconfigure(0, minsize=220) # 左侧边栏
        self.grid_columnconfigure(1, weight=10)   # 中间预览 (自适应)
        self.grid_columnconfigure(2, minsize=340, weight=0) # 右侧列表 (固定宽度，权重0表示不参与抢地盘)
        self.grid_rowconfigure(0, weight=1)

        # 1. 左侧：参数控制
        self.sidebar_frame = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)
        self.setup_sidebar()

        # 2. 中间：视频预览
        self.preview_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.preview_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.setup_preview_area()

        # 3. 右侧：结果列表
        self.list_frame = ctk.CTkFrame(self, width=340, corner_radius=0) # 宽度给足
        self.list_frame.grid(row=0, column=2, sticky="nsew")
        self.list_frame.grid_propagate(False) # 再次加锁
        self.setup_result_list()

    def setup_sidebar(self):
        # 让底部区域自动填充，把按钮顶上去
        self.sidebar_frame.grid_rowconfigure(10, weight=1)

        # 1. Logo
        ctk.CTkLabel(self.sidebar_frame, text="AutoCut\nUltimate", font=ctk.CTkFont(size=22, weight="bold")).grid(row=0, column=0, padx=20, pady=(30, 20))

        # 2. 导入按钮
        self.btn_load = ctk.CTkButton(self.sidebar_frame, text="Step 1: 导入视频", command=self.load_video)
        self.btn_load.grid(row=1, column=0, padx=20, pady=10)

        # 分割线
        ctk.CTkLabel(self.sidebar_frame, text="──────────────", text_color="gray").grid(row=2, column=0, pady=5)

        # 3. 参数调节
        ctk.CTkLabel(self.sidebar_frame, text="灵敏度 (Threshold)", anchor="w").grid(row=3, column=0, padx=20, pady=(5,0), sticky="w")
        self.slider_threshold = ctk.CTkSlider(self.sidebar_frame, from_=1.0, to=10.0, number_of_steps=90, command=self.update_labels)
        self.slider_threshold.set(5.0)
        self.slider_threshold.grid(row=4, column=0, padx=20, pady=(0, 10))
        self.lbl_threshold_val = ctk.CTkLabel(self.sidebar_frame, text="5.0", font=("Consolas", 12))
        self.lbl_threshold_val.grid(row=5, column=0)

        ctk.CTkLabel(self.sidebar_frame, text="最小镜头 (帧数)", anchor="w").grid(row=6, column=0, padx=20, pady=(5,0), sticky="w")
        self.slider_min_len = ctk.CTkSlider(self.sidebar_frame, from_=5, to=60, number_of_steps=55, command=self.update_labels)
        self.slider_min_len.set(12)
        self.slider_min_len.grid(row=7, column=0, padx=20, pady=(0, 10))
        self.lbl_min_len_val = ctk.CTkLabel(self.sidebar_frame, text="12", font=("Consolas", 12))
        self.lbl_min_len_val.grid(row=8, column=0)

        # 4. 核心操作按钮
        self.btn_start = ctk.CTkButton(self.sidebar_frame, text="Step 2: 开始分析", fg_color="green", state="disabled", command=self.start_analysis_thread)
        self.btn_start.grid(row=9, column=0, padx=20, pady=20)
        
        self.btn_stop = ctk.CTkButton(self.sidebar_frame, text="⏹ 停止任务", fg_color="#AA0000", hover_color="#880000", 
                                      state="disabled", command=self.request_stop)
        self.btn_stop.grid(row=10, column=0, padx=20, pady=(0, 20), sticky="s")

        # 5. 进度条 (确保这里只有一段代码！)
        self.progress_bar = ctk.CTkProgressBar(self.sidebar_frame)
        self.progress_bar.grid(row=11, column=0, padx=20, pady=(0, 10), sticky="s")
        self.progress_bar.set(0)

        # 6. 状态文字
        self.lbl_status = ctk.CTkLabel(self.sidebar_frame, text="准备就绪", font=("Arial", 12), text_color="gray")
        self.lbl_status.grid(row=12, column=0, padx=20, pady=(0, 20), sticky="s")
        
    def setup_preview_area(self):
        self.video_display = ctk.CTkLabel(self.preview_frame, text="请导入视频", 
                                          fg_color="#1a1a1a", corner_radius=10)
        self.video_display.pack(expand=True, fill="both", padx=10, pady=(10, 10))

        ctrl_frame = ctk.CTkFrame(self.preview_frame, fg_color="transparent")
        ctrl_frame.pack(fill="x", pady=(0, 10), padx=10)

        self.btn_prev_frame = ctk.CTkButton(ctrl_frame, text="<", width=40, state="disabled", command=lambda: self.seek_relative(-1))
        self.btn_prev_frame.pack(side="left", padx=5)
        
        self.lbl_curr_time = ctk.CTkLabel(ctrl_frame, text="00:00:00:00", font=("Consolas", 18, "bold"))
        self.lbl_curr_time.pack(side="left", padx=10)

        self.btn_next_frame = ctk.CTkButton(ctrl_frame, text=">", width=40, state="disabled", command=lambda: self.seek_relative(1))
        self.btn_next_frame.pack(side="left", padx=5)

        self.btn_add_manual = ctk.CTkButton(ctrl_frame, text="+ 添加当前帧为切点", fg_color="#5555AA", hover_color="#333388", 
                                            state="disabled", command=self.add_manual_point)
        self.btn_add_manual.pack(side="right", padx=10)

    def setup_result_list(self):
        top_bar = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        top_bar.pack(fill="x", pady=5)
        
        ctk.CTkLabel(top_bar, text="切点列表", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10)
        
        btn_frame = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=2)
        
        # --- 修复：增加间距 ---
        ctk.CTkButton(btn_frame, text="全选所有", width=80, height=24, font=("Arial", 11), 
                      command=self.toggle_select_all).pack(side="left", padx=(10, 5)) # 左边距大一点，中间小一点
        
        ctk.CTkButton(btn_frame, text="全选本页", width=80, height=24, font=("Arial", 11), 
                      command=self.toggle_select_page).pack(side="left", padx=5) # 挨着上面那个，但有间隙

        self.result_scroll = ctk.CTkScrollableFrame(self.list_frame, label_text="勾选以导出")
        self.result_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        page_ctrl = ctk.CTkFrame(self.list_frame, fg_color="transparent", height=30)
        page_ctrl.pack(fill="x", pady=2)
        
        self.btn_page_prev = ctk.CTkButton(page_ctrl, text="<", width=30, command=lambda: self.change_page(-1))
        self.btn_page_prev.pack(side="left", padx=10)
        
        self.lbl_page_info = ctk.CTkLabel(page_ctrl, text="Page 1 / 1")
        self.lbl_page_info.pack(side="left", expand=True)
        
        self.btn_page_next = ctk.CTkButton(page_ctrl, text=">", width=30, command=lambda: self.change_page(1))
        self.btn_page_next.pack(side="right", padx=10)

        self.btn_export = ctk.CTkButton(self.list_frame, text="Step 3: 导出选中的片段", fg_color="#D35400", hover_color="#A04000",
                                        height=40, font=ctk.CTkFont(size=16, weight="bold"), command=self.start_export_thread)
        self.btn_export.pack(fill="x", padx=10, pady=10)

    # --- 逻辑功能区 ---

    def update_labels(self, value):
        self.lbl_threshold_val.configure(text=f"{round(self.slider_threshold.get(), 1)}")
        self.lbl_min_len_val.configure(text=f"{int(self.slider_min_len.get())}")

    def load_video(self):
        file_path = filedialog.askopenfilename(filetypes=[("Video Files", "*.mp4 *.mkv *.avi")])
        if file_path:
            self.video_path = file_path
            self.title(f"AutoCut Ultimate - {file_path.split('/')[-1]}")
            if self.cap: self.cap.release()
            self.cap = cv2.VideoCapture(self.video_path)
            self.show_frame(0)
            self.btn_start.configure(state="normal")
            self.btn_prev_frame.configure(state="normal")
            self.btn_next_frame.configure(state="normal")
            self.btn_add_manual.configure(state="normal")

    def request_stop(self):
        if self.is_exporting or self.is_analyzing:
            self.stop_event.set()
            self.btn_stop.configure(text="正在停止...", state="disabled")
            print("用户请求停止...")

    def start_analysis_thread(self):
        self.btn_start.configure(state="disabled", text="分析中...")
        self.btn_stop.configure(state="normal", text="⏹ 停止分析")
        
        # 【修改】不要调用 self.progress_bar.start()
        self.progress_bar.set(0) 
        self.lbl_status.configure(text="正在初始化...") # 更新文字
        
        self.scene_list = []
        self.selected_indices = set()
        self.stop_event.clear()
        self.is_analyzing = True
        
        thread = threading.Thread(target=self.run_analysis)
        thread.start()

    # app.py 中的 run_analysis 方法
    
    def run_analysis(self):
        try:
            curr_th = round(self.slider_threshold.get(), 1)
            curr_min = int(self.slider_min_len.get())
            
            # 【核心修改：线程安全的 UI 更新】
            def update_progress(p):
                # 不要直接调用 set/configure !
                # 用 self.after(0, ...) 把任务扔回主线程
                percent = int(p * 100)
                self.after(0, lambda: self.progress_bar.set(p))
                self.after(0, lambda: self.lbl_status.configure(text=f"分析进度: {percent}%"))

            # 调用后端
            scenes, fps = find_scenes_optimized(
                self.video_path, 
                curr_th, 
                curr_min,
                progress_callback=update_progress,
                stop_event=self.stop_event
            )

            # ================= 核心修复：强制补满进度条 =================
            # 当上面那句代码跑完，说明分析肯定结束了。
            # 无论刚才停在99%还是90%，这里强制设为 100%
            self.after(0, lambda: self.progress_bar.set(1))
            self.after(0, lambda: self.lbl_status.configure(text="分析完成 (100%)"))
            # ==========================================================

            self.scene_list = scenes
            self.fps = fps
            
            # 默认全选
            self.selected_indices = set(range(len(self.scene_list)))
            
            # 检查是否是中途停止
            if self.stop_event.is_set():
                msg = f"分析已手动停止！\n已识别到 {len(scenes)} 个片段。"
                print(msg)
                self.after(0, lambda: self.lbl_status.configure(text="已停止 (显示部分结果)"))
                self.after(0, lambda: messagebox.showinfo("提示", msg))
            
            # 无论是否停止，都去渲染结果列表 (Update UI)
            self.after(0, self.update_ui_after_analysis)
                
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc() # 在终端打印详细报错，方便调试
            
            err_msg = str(e)
            self.after(0, lambda: messagebox.showerror("错误", err_msg))
            self.after(0, lambda: self.btn_start.configure(state="normal", text="重试"))
            self.after(0, lambda: self.lbl_status.configure(text="发生错误"))
        finally:
            self.is_analyzing = False
            self.after(0, lambda: self.btn_stop.configure(state="disabled", text="⏹ 停止任务"))

    def update_ui_after_analysis(self):
        self.progress_bar.set(1)
        self.btn_start.configure(text="重新分析", state="normal")
        self.current_page = 0
        self.render_pagination_list()

    def render_pagination_list(self):
        # 1. 清空当前列表
        for widget in self.result_scroll.winfo_children():
            widget.destroy()

        total_items = len(self.scene_list)
        total_pages = (total_items + self.items_per_page - 1) // self.items_per_page
        if total_pages == 0: total_pages = 1
        
        self.lbl_page_info.configure(text=f"Page {self.current_page + 1} / {total_pages}")
        
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, total_items)
        
        # 2. 渲染行 (使用 grid 布局实现完美对齐)
        for i in range(start_idx, end_idx):
            scene = self.scene_list[i]
            start_frame = scene[0]
            time_str = frames_to_timecode_premiere(start_frame, self.fps)
            
            row = ctk.CTkFrame(self.result_scroll, fg_color="transparent")
            row.pack(fill="x", pady=2)
            
            # --- 关键：行内布局 ---
            # Col 0: 复选框 (Sticky W 靠左)
            # Col 1: 弹簧 (Weight 1, 把后面挤到右边)
            # Col 2: 眼睛
            # Col 3: 删除
            row.grid_columnconfigure(1, weight=1) 
            
            chk_var = ctk.BooleanVar(value=(i in self.selected_indices))
            chk = ctk.CTkCheckBox(row, text=f"[{i+1}] {time_str}", font=("Consolas", 12), width=100,
                                  variable=chk_var, command=lambda idx=i, v=chk_var: self.on_check(idx, v))
            chk.grid(row=0, column=0, sticky="w", padx=5)
            
            # 空 Label 占位，把后面推到右边
            ctk.CTkLabel(row, text="").grid(row=0, column=1) 

            # 眼睛 (固定尺寸)
            ctk.CTkButton(row, text="👁", width=30, height=24, fg_color="#444", 
                          command=lambda f=start_frame: self.show_frame(f)).grid(row=0, column=2, padx=2)

            # 删除 (固定尺寸)
            ctk.CTkButton(row, text="×", width=30, height=24, fg_color="#AA0000", hover_color="#FF0000",
                          command=lambda idx=i: self.delete_item(idx)).grid(row=0, column=3, padx=5)

    def change_page(self, delta):
        total_items = len(self.scene_list)
        total_pages = (total_items + self.items_per_page - 1) // self.items_per_page
        new_page = self.current_page + delta
        if 0 <= new_page < total_pages:
            self.current_page = new_page
            self.render_pagination_list()

    def on_check(self, index, var):
        if var.get():
            self.selected_indices.add(index)
        else:
            self.selected_indices.discard(index)

    def toggle_select_all(self):
        if len(self.selected_indices) == len(self.scene_list):
            self.selected_indices.clear()
        else:
            self.selected_indices = set(range(len(self.scene_list)))
        self.render_pagination_list()

    def toggle_select_page(self):
        total_items = len(self.scene_list)
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, total_items)
        page_indices = set(range(start_idx, end_idx))
        if page_indices.issubset(self.selected_indices):
            self.selected_indices -= page_indices
        else:
            self.selected_indices.update(page_indices)
        self.render_pagination_list()

    def delete_item(self, index):
        self.scene_list.pop(index)
        new_selected = set()
        for idx in self.selected_indices:
            if idx < index:
                new_selected.add(idx)
            elif idx > index:
                new_selected.add(idx - 1)
        self.selected_indices = new_selected
        self.render_pagination_list()

    def add_manual_point(self):
        new_frame = self.current_frame_idx
        existing_frames = [s[0] for s in self.scene_list]
        if new_frame in existing_frames:
            messagebox.showinfo("提示", "该帧已经是切点了")
            return
            
        self.scene_list.append((new_frame, None))
        self.scene_list.sort(key=lambda x: x[0])
        
        new_index = [s[0] for s in self.scene_list].index(new_frame)
        new_selected = set()
        for idx in self.selected_indices:
            if idx < new_index:
                new_selected.add(idx)
            else:
                new_selected.add(idx + 1)
        new_selected.add(new_index)
        self.selected_indices = new_selected
        
        self.current_page = new_index // self.items_per_page
        self.render_pagination_list()
        messagebox.showinfo("成功", f"已添加第 {new_frame} 帧为新切点")

    def show_frame(self, frame_num):
        if not self.cap: return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = self.cap.read()
        if ret:
            self.current_frame_idx = frame_num
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(frame_rgb)
            
            # --- 修复：防止 UI 挤压 ---
            # 严格读取 preview_frame 的尺寸，并减去一定的边距
            container_w = self.preview_frame.winfo_width()
            container_h = self.preview_frame.winfo_height()
            
            if container_w < 100: container_w = 640
            if container_h < 100: container_h = 360
            
            # 关键：稍微缩小一点点 (margin)，确保不会撑满导致 grid 重新计算
            target_w = container_w - 20
            target_h = container_h - 20

            img_ratio = pil_image.width / pil_image.height
            container_ratio = target_w / target_h
            
            if container_ratio > img_ratio:
                final_h = target_h
                final_w = int(target_h * img_ratio)
            else:
                final_w = target_w
                final_h = int(target_w / img_ratio)
            
            ctk_img = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(final_w, final_h))
            
            self.video_display.configure(image=ctk_img, text="")
            time_str = frames_to_timecode_premiere(frame_num, self.fps)
            self.lbl_curr_time.configure(text=f"{time_str}")

    def seek_relative(self, delta):
        if self.cap:
            new_frame = max(0, self.current_frame_idx + delta)
            self.show_frame(new_frame)

    def start_export_thread(self):
        if not self.scene_list: return
        if not self.selected_indices:
            messagebox.showwarning("提示", "请至少勾选一个片段！")
            return
            
        save_dir = filedialog.askdirectory(title="选择导出文件夹")
        if not save_dir: return

        use_custom_name = messagebox.askyesno("命名设置", "是否需要自定义导出文件的前缀？\n(选择'否'将使用默认命名 'clip_xxx')")
        
        base_name = "clip"
        if use_custom_name:
            dialog = ctk.CTkInputDialog(text="请输入文件名前缀 (例如: Naruto_Ep1):", title="自定义命名")
            input_text = dialog.get_input()
            if input_text and input_text.strip():
                base_name = input_text.strip()
        
        self.btn_export.configure(state="disabled", text="正在导出中...")
        self.btn_stop.configure(state="normal", text="⏹ 停止导出")
        self.stop_event.clear()
        self.is_exporting = True
        
        thread = threading.Thread(target=self.run_export, args=(save_dir, base_name))
        thread.start()

    # app.py 中的 run_export 方法
    def run_export(self, save_dir, base_name):
        try:
            # 1. 准备数据
            all_points = [s[0] for s in self.scene_list]
            total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            sorted_indices = sorted(list(self.selected_indices))
            
            items_to_export = []
            for idx in sorted_indices:
                start_frame = all_points[idx]
                if idx < len(all_points) - 1:
                    end_frame = all_points[idx + 1]
                else:
                    end_frame = total_frames
                items_to_export.append((start_frame, end_frame))
            
            # 2. 定义导出进度回调
            def update_export_progress(p):
                # 更新按钮文字显示百分比
                self.btn_export.configure(text=f"导出中 ({int(p*100)}%)...")

            # 3. 【关键修改】调用后端新函数
            success_count = export_video_clips(
                self.video_path,
                items_to_export,
                save_dir,
                base_name=base_name,
                progress_callback=update_export_progress,
                stop_event=self.stop_event
            )

            if self.stop_event.is_set():
                 self.after(0, lambda: messagebox.showinfo("已停止", f"导出已中断！\n成功导出: {success_count} 个文件"))
            else:
                 self.after(0, lambda: messagebox.showinfo("成功", f"导出完成！\n共导出 {success_count} 个片段"))
            
        except Exception as e:
            err_msg = str(e)
            print(err_msg)
            self.after(0, lambda m=err_msg: messagebox.showerror("导出失败", str(m)))
        finally:
             self.is_exporting = False
             self.after(0, lambda: self.btn_export.configure(state="normal", text="Step 3: 导出选中的片段"))
             self.after(0, lambda: self.btn_stop.configure(state="disabled", text="⏹ 停止任务"))

if __name__ == "__main__":
    app = AutoCutApp()
    app.mainloop()