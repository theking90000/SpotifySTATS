async function loadpage(params) {
  try {
    const content = await $.get(params);
    $("main").html(content);
  } catch (error) {
    console.error("Error loading page:", error);
    $("main").html("<p>Error loading page content</p>");
  }
}

const fetchQueue = {
  queue: [],
  running: 0,
  maxParallel: 2,

  add: function (task) {
    return new Promise((resolve, reject) => {
      this.queue.push({ task, resolve, reject });
      this.processQueue();
    });
  },

  processQueue: function () {
    while (this.running < this.maxParallel && this.queue.length > 0) {
      const task = this.queue.shift();
      if (!task) break;
      this.running++;

      task
        .task()
        .then((data) => {
          this.running--;
          last = Date.now();
          task.resolve(data);
          this.processQueue();
        })
        .catch((error) => {
          this.running--;
          last = Date.now();
          task.reject(error);
          this.processQueue();
        });
    }
  },
};
