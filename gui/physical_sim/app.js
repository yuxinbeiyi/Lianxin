(() => {
  const canvas = document.querySelector("#world");
  const context = canvas.getContext("2d");
  const connection = document.querySelector("#connection");
  const hint = document.querySelector("#hint");
  const log = document.querySelector("#log");
  const telemetry = document.querySelector("#telemetry");
  const showGrid = document.querySelector("#show-grid");
  const showPath = document.querySelector("#show-path");
  let mode = "marker";
  let snapshot = null;
  let socket = null;
  let dragStart = null;
  let seenEvents = new Set();
  let navigationPending = false;

  const command = (payload) => {
    if (socket?.readyState !== WebSocket.OPEN) {
      appendLog("服务未连接，命令未发送。");
      return;
    }
    socket.send(JSON.stringify(payload));
  };

  function connect() {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${protocol}://${location.host}/ws`);
    socket.addEventListener("open", () => setConnection(true));
    socket.addEventListener("close", () => {
      setConnection(false);
      window.setTimeout(connect, 1200);
    });
    socket.addEventListener("message", ({ data }) => receive(JSON.parse(data)));
  }

  function receive(payload) {
    if (payload.type === "world_snapshot") {
      snapshot = payload;
      const activeTask = payload.task;
      navigationPending = Boolean(activeTask && !["ARRIVED", "NO_PATH", "INVALID_GOAL", "BLOCKED", "CANCELLED"].includes(activeTask.status));
      document.querySelector("#navigate").disabled = navigationPending;
      updateTelemetry();
      for (const event of payload.events || []) {
        const key = `${event.task_id}:${event.type}:${event.status}:${event.error}`;
        if (!seenEvents.has(key)) {
          seenEvents.add(key);
          appendLog(`${event.task_id} · ${event.type} · ${event.status}${event.error ? ` · ${event.error}` : ""}`);
        }
      }
      render();
    } else if (payload.type === "ack") {
      appendLog(payload.message + (payload.task_id ? ` (${payload.task_id})` : ""));
    } else if (payload.type === "error") {
      appendLog(`错误：${payload.message}`);
    }
  }

  function setConnection(online) {
    connection.textContent = online ? "服务已连接" : "正在重连";
    connection.className = `status-chip ${online ? "online" : "offline"}`;
  }

  function updateTelemetry() {
    if (!snapshot) return;
    const task = snapshot.task;
    telemetry.innerHTML = [
      ["任务", task ? `${task.kind} / ${task.status}` : "空闲"],
      ["蛇头", `${snapshot.snake.body[0][0]}, ${snapshot.snake.body[0][1]}`],
      ["方向", snapshot.snake.direction],
      ["步频", `${snapshot.snake.speed.toFixed(1)} 格/s`],
      ["路径", task ? `${task.path_index} / ${task.path_length}` : "—"],
    ].map(([title, value]) => `<div><dt>${title}</dt><dd>${value}</dd></div>`).join("");
  }

  function render() {
    if (!snapshot) return;
    const { width, height } = snapshot.world;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#d6dfd4";
    context.fillRect(0, 0, width, height);
    if (showGrid.checked) drawGrid(width, height);
    drawObstacles(snapshot.obstacles);
    if (showPath.checked) drawPath(snapshot.path);
    drawFood(snapshot.markers);
    drawSnake(snapshot.snake);
  }

  function drawGrid(width, height) {
    context.strokeStyle = "rgba(42, 63, 64, .16)";
    context.lineWidth = 1;
    for (let coordinate = 0; coordinate <= width; coordinate += 20) {
      context.beginPath(); context.moveTo(coordinate, 0); context.lineTo(coordinate, height); context.stroke();
    }
    for (let coordinate = 0; coordinate <= height; coordinate += 20) {
      context.beginPath(); context.moveTo(0, coordinate); context.lineTo(width, coordinate); context.stroke();
    }
  }

  function drawObstacles(obstacles) {
    context.fillStyle = "#536171";
    for (const obstacle of obstacles) context.fillRect(obstacle.x, obstacle.y, obstacle.w, obstacle.h);
  }

  function drawPath(path) {
    if (!path?.length) return;
    context.save();
    context.strokeStyle = "#287ed0";
    context.lineWidth = 4;
    context.setLineDash([7, 6]);
    context.beginPath();
    path.forEach(([x, y], index) => index ? context.lineTo(x, y) : context.moveTo(x, y));
    context.stroke();
    context.restore();
  }

  function drawFood(markers) {
    for (const marker of markers) {
      context.fillStyle = marker.active ? "#f5c842" : "#bc952b";
      context.fillRect(marker.x - 8, marker.y - 8, 16, 16);
      context.strokeStyle = "#fff0a6";
      context.lineWidth = 2;
      context.strokeRect(marker.x - 8, marker.y - 8, 16, 16);
    }
  }

  function drawSnake(snake) {
    snake.body.forEach(([x, y], index) => {
      context.fillStyle = index === 0 ? "#e14b52" : "#42a86d";
      context.fillRect(x - 8, y - 8, 16, 16);
      context.strokeStyle = "#e9fff0";
      context.lineWidth = 1;
      context.strokeRect(x - 8, y - 8, 16, 16);
    });
  }

  function canvasPoint(event) {
    const bounds = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - bounds.left) * canvas.width / bounds.width,
      y: (event.clientY - bounds.top) * canvas.height / bounds.height,
    };
  }

  function appendLog(message) {
    const item = document.createElement("li");
    item.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    log.prepend(item);
    while (log.children.length > 50) log.lastChild.remove();
  }

  document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
    mode = button.dataset.mode;
    document.querySelectorAll("[data-mode]").forEach((item) => item.classList.toggle("active", item === button));
    hint.textContent = { marker: "点击地图放置黄色食物。", obstacle: "拖拽地图绘制矩形障碍物。", erase: "点击障碍物即可删除。" }[mode];
  }));
  canvas.addEventListener("pointerdown", (event) => {
    if (mode === "obstacle") dragStart = canvasPoint(event);
  });
  canvas.addEventListener("pointerup", (event) => {
    const point = canvasPoint(event);
    if (mode === "marker") command({ type: "place_marker", ...point });
    if (mode === "erase") command({ type: "remove_obstacle", ...point });
    if (mode === "obstacle" && dragStart) {
      const x = Math.min(dragStart.x, point.x), y = Math.min(dragStart.y, point.y);
      const w = Math.abs(point.x - dragStart.x), h = Math.abs(point.y - dragStart.y);
      if (w >= 10 && h >= 10) command({ type: "add_obstacle", x, y, w, h });
    }
    dragStart = null;
  });
  document.querySelector("#navigate").onclick = () => {
    if (navigationPending) return;
    navigationPending = true;
    document.querySelector("#navigate").disabled = true;
    command({ type: "start_debug_navigation" });
  };
  document.querySelector("#move-up").onclick = () => command({ type: "manual_move", direction: "up" });
  document.querySelector("#move-down").onclick = () => command({ type: "manual_move", direction: "down" });
  document.querySelector("#move-left").onclick = () => command({ type: "manual_move", direction: "left" });
  document.querySelector("#move-right").onclick = () => command({ type: "manual_move", direction: "right" });
  document.querySelector("#cancel").onclick = () => command({ type: "cancel_task" });
  document.querySelector("#stop").onclick = () => command({ type: "emergency_stop" });
  document.querySelector("#clear-obstacles").onclick = () => command({ type: "clear_obstacles" });
  document.querySelector("#reset").onclick = () => command({ type: "reset" });
  document.querySelector("#download-debug").onclick = () => window.open("/debug/report", "_blank");
  showGrid.onchange = render;
  showPath.onchange = render;
  connect();
})();
