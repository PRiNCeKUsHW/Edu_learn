"""Tighten Chapter now that 0006 has repointed every row onto Subject.

Step 3 of 4. DDL only, no RunPython -- see 0005's docstring for why that
separation matters on PostgreSQL. 0006's data write already committed in its
own transaction, so ALTER TABLE core_chapter here has no pending FK-trigger
events left over from it to collide with.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_invert_hierarchy_data'),
    ]

    operations = [
        migrations.AlterField(
            model_name='chapter',
            name='subject',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='chapters', to='core.subject'),
        ),
        migrations.RemoveField(model_name='chapter', name='class_level'),
        migrations.AlterUniqueTogether(
            name='chapter', unique_together={('subject', 'slug')},
        ),
    ]
