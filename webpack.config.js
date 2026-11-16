var BundleTracker = require('webpack-bundle-tracker'),
    MiniCssExtractPlugin = require('mini-css-extract-plugin'),
    CopyPlugin = require('copy-webpack-plugin'),
    path = require('path'),
    webpack = require('webpack'),
    loaders = [
        {
            loader: 'css-loader'
        },
        {
            loader: 'sass-loader',
            options: {
                sassOptions: {
                    includePaths: [path.resolve('./sass/')]
                }
            }
        }
    ],
    context = path.join(__dirname, 'course_discovery/static');

module.exports = {
    context: context,
    mode: 'production',

    entry: {
        'base.style': './sass/main-ltr.scss',
        'base.style-rtl': './sass/main-rtl.scss',
    },

    output: {
        path: path.join(context, './bundles/'),
        filename: '[name]-[hash].js'
    },

    plugins: [
        new BundleTracker({filename: './webpack-stats.json'}),
        new webpack.ProvidePlugin({
            $: 'jquery',
            jQuery: 'jquery',
            'window.jQuery': 'jquery'
        }),
        new MiniCssExtractPlugin({
            filename: '[name]-[hash].css'
        }),
        // jquery-ui is loaded directly by Django admin (ProgramAdmin.Media),
        // so copy its UMD bundle into the static bundles dir instead of
        // bundling it. This replaces the old bower_components/ path.
        new CopyPlugin([
            {
                from: path.resolve(__dirname, 'node_modules/jquery-ui/dist/jquery-ui.min.js'),
                to: 'jquery-ui.min.js'
            }
        ])
    ],

    module: {
        rules: [
            {
                test: /\.s?css$/,
                use: [MiniCssExtractPlugin.loader].concat(loaders)
            },
            {
                test: /\.woff2?$/,
                // Inline small woff files and output them below font
                use: [{
                    loader: 'file-loader',
                    options: {
                        name: 'font/[name]-[hash].[ext]'
                    }
                }]
            },
            {
                test: /\.(ttf|eot|svg)$/,
                use: [{
                    loader: 'file-loader',
                    options: {
                        name: 'font/[name]-[hash].[ext]'
                    }
                }]
            },
            {
                test: require.resolve('datatables.net'),
                use: 'imports-loader?define=>false'
            },
            {
                test: require.resolve('datatables.net-bs'),
                use: 'imports-loader?define=>false'
            }
        ]
    },
    resolve: {
        modules: ['node_modules'],
        extensions: ['.css', '.js', '.scss']
    }
};
