const path = require('path');
const BundleTracker = require('webpack-bundle-tracker');
const MiniCssExtractPlugin = require('mini-css-extract-plugin')
const webpack = require('webpack');

const mode = process.argv.indexOf("production") !== -1 ? "production" : "development";
console.log(`Webpack mode: ${mode}`);

let plugins = [
  new BundleTracker({ path: __dirname, filename: 'webpack-stats.json' }),
  new MiniCssExtractPlugin({
    filename: 'css/[name].[contenthash].css',
  }),
  // Supplies jQuery to bundled modules that use $ / jQuery as free variables
  // without importing it (e.g. file_upload_widget.js).
  //
  // "default" is required: jQuery 4 is an ES module, so a bare 'jquery' here
  // binds the namespace object rather than the function, and calls fail with
  // "$ is not a function".
  //
  // 'window.jQuery' is deliberately NOT mapped. ProvidePlugin rewrites the
  // configured expression wherever it appears, including on the left-hand side
  // of an assignment, so mapping it turned the "window.jQuery = jQuery" line in
  // index.js into a no-op and left the global unset in the production build.
  new webpack.ProvidePlugin({
    $: ['jquery', 'default'],
    jQuery: ['jquery', 'default'],
  }),
];

if (mode === 'development') {
  // Only add LiveReloadPlugin in development mode
  const LiveReloadPlugin = require('webpack-livereload-plugin');
  plugins.push(new LiveReloadPlugin({ appendScriptTag: true }));
}


// Globals for out-of-bundle scripts are published explicitly at the top of
// static/js/index.js rather than through expose-loader. See the comment there:
// expose-loader matched on require.resolve(), which resolves jQuery 4 and
// DataTables 3 to their CJS build while webpack bundles the ESM one, so the
// rules matched nothing and failed silently.

module.exports = {
  entry: './static/js/index',
  output: {
    path: path.resolve('./static/bundles'),
    filename: "[name].[contenthash].js"
  },
  plugins: plugins,
  module: {
    rules: [
      {
        test: /\.scss$/,
        use: [
            MiniCssExtractPlugin.loader,
            {
              loader: 'css-loader'
            },
            {
              loader: 'sass-loader',
              options: {
                sourceMap: true
              }
            }
          ]
      }
    ],
  },
  stats: {
    assets: false,           // Hide assets info
    chunks: false,           // Hide chunks info
    modules: false,          // Hide modules info
    entrypoints: false,      // Hide entrypoints info
    performance: false,      // Hide performance info
    errors: true,            // Show only errors
    errorDetails: true,      // Include detailed error messages
    warnings: true,          // Show warnings
    builtAt: true,           // Show when the build was created
    colors: true,            // Colorized output
  },
};
