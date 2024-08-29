const path = require('path');
const BundleTracker = require('webpack-bundle-tracker');
const MiniCssExtractPlugin = require('mini-css-extract-plugin')

const mode = process.argv.indexOf("production") !== -1 ? "production" : "development";
console.log(`Webpack mode: ${mode}`);

let plugins = [
  new BundleTracker({ path: __dirname, filename: 'webpack-stats.json' }),
  new MiniCssExtractPlugin({
    filename: 'css/[name].[contenthash].css',
  }),
];

if (mode === 'development') {
  // Only add LiveReloadPlugin in development mode
  const LiveReloadPlugin = require('webpack-livereload-plugin');
  plugins.push(new LiveReloadPlugin({ appendScriptTag: true }));
}

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
