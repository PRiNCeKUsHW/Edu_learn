"""Tighten Subject and retire ClassLevel now that 0008 has pruned it empty.

Step 4 of 4b. DDL only, no RunPython -- see 0005's docstring. 0008's DELETE
already committed in its own transaction (and cascaded ClassLevel to empty),
so these ALTER TABLE / DROP TABLE statements have no pending FK-trigger
events left over from that write to collide with.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_prune_old_subjects'),
    ]

    operations = [
        migrations.AlterField(
            model_name='subject',
            name='klass',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='subjects', to='core.class', verbose_name='class'),
        ),
        migrations.RemoveField(model_name='subject', name='kind'),
        migrations.AlterModelOptions(
            name='subject', options={'ordering': ['order', 'name']},
        ),
        migrations.AlterUniqueTogether(
            name='subject', unique_together={('klass', 'slug')},
        ),

        migrations.AlterUniqueTogether(name='classlevel', unique_together=set()),
        migrations.RemoveField(model_name='classlevel', name='subject'),
        migrations.DeleteModel(name='ClassLevel'),
    ]
