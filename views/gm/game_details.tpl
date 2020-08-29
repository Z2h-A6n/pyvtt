%import time, os
%include("header", title='Setup: {0}'.format(game.title))

<div class="menu">

<h1>Storyboard: {{game.title}}</a></h1>
%if game.active != '':
<a href="http://{{server}}/play/{{game.title}}" target="_blank">Play</a>
%end

<form action="/gm/{{game.title}}/create" id="create" method="post">
	Create Scene with Title: <input type="text" name="scene_title" value="untitled" />
	<input type="submit" value="Create" />
</form>

<h2>Available Scenes:</h2>
<table>
%for s in game.scenes.order_by(lambda s: s.id):
	<tr>
	%if s.title == game.active:
		<td><b><i>{{s.title}}</i></b></td>
	%else:
		<td><a href="/gm/{{game.title}}/activate/{{s.title}}">{{s.title}}</a></td>
	%end
		<td style="width: 50px;"></td>
		<td><a href="/gm/{{game.title}}/clone/{{s.title}}"><img src="/static/copy.png" title="duplicate" /></a></td>
		<td style="width: 50px;"></td>
		<td><form id="#form_{{s.title}}'" action="/gm/{{game.title}}/rename/{{s.title}}" id="rename_{{s.id}}" method="post">
			<input type="text" name="scene_title" value="" />
			<input type="image" src="/static/rename.png" title="rename">
		</form></td>
		<td style="width: 50px;"></td>
		<td><a href="/gm/{{game.title}}/delete/{{s.title}}"><img src="/static/delete.png" title="delete" /></a></td>
	</tr>
%end
</table>

<h2>Latest Rolls:</h2>

<ul>
%now = int(time.time())
%num_old = 0
%for r in game.rolls:
	%if r.timeid > now - 60:
	<li>{{r.player}} D{{r.sides}} = {{r.result}}</li>
	%else:
		%num_old += 1
	%end
%end
%if num_old == 0:
	no old rolls yet
%end
</ul>
<a href="/gm/{{game.title}}/clearRolls">clear old rolls ({{num_old}})</a> <hr />

%abandoned = game.getAbandonedImages()
%size = 0
%for fname in abandoned:
	%size += os.path.getsize(fname)
%end
%if size < 1024:
	%size = '<1 KB'
%else:
	%size /= 1024.0
	%if size < 1024:
		%size = '{0} KB'.format(int(size))
	%else:
		%size = '{0} MB'.format(int(size / 1024))
	%end
%end
%if len(abandoned) > 0:
	%abandoned = '{0}x, {1}'.format(len(abandoned), size)
%else:
	%abandoned = '0'
%end
<a href="/gm/{{game.title}}/clearImages">clear abandoned images ({{abandoned}})</a> <hr />

<a href="/">Back to Games Overview</a>

<hr />

<a href="/setup/delete/{{game.title}}">Delete Game</a>

</div>

%include("footer")
