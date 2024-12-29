async function loadpage(params) {
  try {
    const content = await $.get(params);
    $("main").html(content);
  } catch (error) {
    console.error("Error loading page:", error);
    $("main").html("<p>Error loading page content</p>");
  }
}
