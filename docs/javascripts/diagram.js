// A diagram shrinks to fit the column, which leaves its text too small to
// read; enlarging it moves it into a full-screen dialog at its own size.
const button = (text) =>
  Object.assign(document.createElement("button"), {
    type: "button",
    textContent: text,
  });

for (const diagram of document.querySelectorAll(".diagram")) {
  const svg = diagram.querySelector("svg");
  const enlarge = button("Enlarge diagram");
  const dialog = document.createElement("dialog");
  dialog.append(button("Close"));
  diagram.append(enlarge, dialog);

  // A click on the figure or its button opens; any click in the open dialog
  // closes it. Escape is the dialog's own.
  diagram.addEventListener("click", () => {
    if (dialog.open) {
      dialog.close();
    } else {
      dialog.append(svg);
      dialog.showModal();
    }
  });
  dialog.addEventListener("close", () => enlarge.before(svg));
}
