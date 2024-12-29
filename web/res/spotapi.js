function _manager(getter) {
  return {
    data: new Map(),
    get: function (id) {
      let pr = this.data.get(id);
      if (pr) return pr;
      pr = fetchQueue.add(() => getter(id));
      this.data.set(id, pr);
      return pr;
    },
  };
}

const tracks = _manager((id) =>
  $.getJSON(window.api_endpoint + "/track/" + id)
);

const tracksBulk = _manager((ids) =>
  $.getJSON(window.api_endpoint + "/tracks/" + ids.join(","))
);

$(document).ready(async () => {
  // -- [data-cover] --
  let ids = $("img[data-cover]")
    .map((i, el) => $(el).data("cover"))
    .get();
  while (ids.length > 0) {
    const data = await tracksBulk.get(ids.splice(0, 50));
    ids = ids.splice(50);
    $("img[data-cover]").each((i, img) => {
      const d = data.tracks[i];
      const lowRes = d.album.images.find((x) => x.width === 64);
      if (lowRes) $(img).attr("src", lowRes.url).attr("alt", data.name);
      else {
      }
      //$(img).attr("src", data.images);
    });
  }
});

$(document).ready(async () => {
  // -- [data-cover-artist] --
  let ids = $("img[data-cover-artist]")
    .map((i, el) => $(el).data("cover-artist"))
    .get();
  while (ids.length > 0) {
    const data = await tracksBulk.get(ids.splice(0, 50));
    ids = ids.splice(50);
    $("img[data-cover-artist]").each((i, img) => {
      const d = data.tracks[i];
      const lowRes = d.album.images.find((x) => x.width === 64);
      if (lowRes) $(img).attr("src", lowRes.url).attr("alt", data.name);
      else {
      }
      //$(img).attr("src", data.images);
    });
  }
});
