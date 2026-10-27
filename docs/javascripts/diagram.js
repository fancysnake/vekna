// A diagram is drawn 1400px wide and shrinks to fit the column, which leaves
// its text too small to read; a click lifts it to full screen at its own size.
const ENLARGE = "Enlarge diagram";

const toggle = (diagram) => {
  const opening = !diagram.classList.contains("is-open");
  diagram.classList.toggle("is-open", opening);
  diagram.setAttribute("aria-label", opening ? "Close diagram" : ENLARGE);
  document.body.style.overflow = opening ? "hidden" : "";
};

// `document$` fires on every page load, instant navigation included.
document$.subscribe(() => {
  for (const diagram of document.querySelectorAll(".diagram")) {
    diagram.tabIndex = 0;
    diagram.setAttribute("role", "button");
    diagram.setAttribute("aria-label", ENLARGE);
  }
});

document.addEventListener("click", (event) => {
  const diagram = event.target.closest(".diagram");
  if (diagram) toggle(diagram);
});

document.addEventListener("keydown", (event) => {
  const open = document.querySelector(".diagram.is-open");
  if (event.key === "Escape" && open) {
    toggle(open);
  } else if (
    (event.key === "Enter" || event.key === " ") &&
    event.target.classList?.contains("diagram")
  ) {
    event.preventDefault();
    toggle(event.target);
  }
});
