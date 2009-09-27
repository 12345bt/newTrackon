<%inherit file="base.mako"/>
<%page cached="False"/>

<div class=grid_12>
% for t in trackers_info:
    <% ti = trackers_info[t] %>
    <form action="/admin" method="POST"><fieldset>
        <input type="text" name="address" value="${t}">
        <input type="text" name="name" value="${ti.get('name', t)}">
        <input type="text" name="home" value="${ti.get('home', '')}">
        
        <input type="submit" name="action" value="Delete">
        <input type="submit" name="action" value="Update">
    </fieldset></form>
% endfor
</div>