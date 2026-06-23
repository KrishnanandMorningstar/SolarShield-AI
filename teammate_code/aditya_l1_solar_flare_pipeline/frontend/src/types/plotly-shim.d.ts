declare module "plotly.js-dist-min" {
  // The dist-min bundle ships no types; we use it imperatively as `any`.
  const Plotly: any;
  export default Plotly;
}
