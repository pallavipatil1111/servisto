/** Tailwind is compiled into static/css/tailwind.css, so no CDN script is needed at runtime. */
module.exports = {
  content: ['./templates/**/*.html', './static/js/**/*.js', './main.py'],
  theme: { extend: {} },
  plugins: [],
};
