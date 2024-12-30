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

const artistsBulk = _manager((ids) =>
  $.getJSON(window.api_endpoint + "/artists/" + ids.join(","))
);

async function loadTableData(container) {
  async function tracks() {
    const items = $(container).find("img[data-cover]");
    let ids = items.map((i, el) => $(el).data("cover")).get();
    let p = 0;
    while (p < ids.length) {
      const data = await tracksBulk.get(ids.slice(p, p + 50));
      items.each((i, img) => {
        if (i < p || i >= p + 50) return;
        const d = data.tracks[i - p];
        if (!d.album) return;
        const lowRes =
          d.album.images.find((x) => x.width === 64) || d.album.images[0];
        if (lowRes) $(img).attr("src", lowRes.url).attr("alt", data.name);
        else {
        }
        //$(img).attr("src", data.images);
      });
      p += 50;
    }
  }

  async function artists() {
    const items = $(container).find("img[data-cover-artist]");
    let ids = items.map((i, el) => $(el).data("cover-artist")).get();
    let p = 0;
    let artists = [];
    while (p < ids.length) {
      const data = await tracksBulk.get(ids.splice(0, 50));
      items.each((i, img) => {
        if (i < p || i >= p + 50) return;
        const d = data.tracks[i - p];
        if (!d.artists[0]) return;
        artists.push(d.artists[0].uri);
      });
      p += 50;
    }

    p = 0;
    while (p < artists.length) {
      const data = await artistsBulk.get(artists.splice(0, 50));
      items.each((i, img) => {
        if (i < p || i >= p + 50) return;
        const d = data.artists[i - p];
        if (!d) return;
        const image = d.images.find((x) => x.width === 160);
        if (image) $(img).attr("src", image.url).attr("alt", d.name);
      });
      p += 50;
    }
  }

  return Promise.all([tracks(), artists()]);
}

$(document).ready(function () {
  loadTableData("body");
});
