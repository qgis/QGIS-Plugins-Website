require('../style/scss/style.scss');

import jQuery from 'jquery';
import './file_upload_widget.js';
import DataTable from 'datatables.net';
import 'datatables.net-dt';

import Choices from 'choices.js';
import 'choices.js/src/styles/choices.scss';

// Hand jQuery to DataTables. The DataTables 3 ES module no longer imports
// jQuery itself, so without this it never registers the $.fn.dataTable plugin
// and the versions table in plugin_detail.html fails with
// "$(...).DataTable is not a function".
DataTable.use(jQuery);

// Publish the globals that scripts outside the bundle depend on:
// static/js/jquery.cookie.js, jquery.ratings, dataTables.bulma.js and the
// inline setup in plugin_detail.html are plain <script> tags and expect
// window.$ / window.jQuery.
//
// This was previously done with expose-loader, keyed on require.resolve().
// jQuery 4 and DataTables 3 ship dual CJS/ESM builds and the two resolvers
// disagree: require.resolve() picks the "node" condition (dist/jquery.js, UMD)
// while webpack bundles the "import" one (dist-module/jquery.module.js). The
// loader rule matched a file that was never in the graph, so it exposed nothing
// and failed silently. Assigning here does not depend on those conditions
// lining up.
//
// Kept as separate statements: written as a chain
// (window.$ = window.jQuery = jQuery) the production minifier keeps only
// window.$ and drops the rest.
window.jQuery = jQuery;
window.$ = jQuery;
window.DataTable = DataTable;

 document.addEventListener('DOMContentLoaded', () => {

     // Get all "navbar-burger" elements
     const $navbarBurgers = Array.prototype.slice.call(
         document.querySelectorAll('.navbar-burger'), 0);

     // Add a click event on each of them
     $navbarBurgers.forEach( el => {
       el.addEventListener('click', () => {

         // Get the target from the "data-target" attribute
         const target = el.dataset.target;
         const $target = document.getElementById(target);

         // Toggle the "is-active" class on both the "navbar-burger" and the "navbar-menu"
         el.classList.toggle('is-active');
         $target.classList.toggle('is-active');

       });
     });

    window.Choices = Choices;

   }); 