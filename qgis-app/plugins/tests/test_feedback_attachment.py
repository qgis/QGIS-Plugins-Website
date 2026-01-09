import os
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import InMemoryUploadedFile, SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image
from plugins.models import (
    Plugin,
    PluginVersion,
    PluginVersionFeedback,
    PluginVersionFeedbackAttachment,
)


def create_test_image(filename="test.png", size=(100, 100), color="red"):
    """
    Helper function to create a test image file
    """
    image = Image.new("RGB", size, color)
    img_io = BytesIO()
    image.save(img_io, format="PNG")
    img_io.seek(0)
    return InMemoryUploadedFile(
        img_io,
        "ImageField",
        filename,
        "image/png",
        img_io.getbuffer().nbytes,
        None,
    )


def create_simple_test_image(filename="test.png"):
    """
    Helper function to create a simple uploaded file
    """
    # Create a simple 1x1 PNG image
    img = Image.new("RGB", (1, 1), color="red")
    img_io = BytesIO()
    img.save(img_io, format="PNG")
    img_io.seek(0)
    return SimpleUploadedFile(filename, img_io.read(), content_type="image/png")


class PluginVersionFeedbackAttachmentModelTest(TestCase):
    """Test the PluginVersionFeedbackAttachment model"""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.creator = User.objects.get(id=2)
        self.staff = User.objects.get(id=3)
        self.plugin = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-feedback-attachment",
            name="test feedback attachment plugin",
            about="this is a test for plugin feedback attachments",
        )
        self.version = PluginVersion.objects.create(
            plugin=self.plugin,
            created_by=self.creator,
            min_qg_version="3.0.0",
            max_qg_version="3.99.99",
            version="0.1",
            approved=False,
            external_deps="test",
        )
        self.feedback = PluginVersionFeedback.objects.create(
            version=self.version, reviewer=self.staff, task="test feedback task"
        )

    def test_create_attachment_success(self):
        """Test creating an attachment with all required fields"""
        image = create_test_image()
        attachment = PluginVersionFeedbackAttachment.objects.create(
            feedback=self.feedback, image=image, caption="Test image caption"
        )

        self.assertIsNotNone(attachment.id)
        self.assertEqual(attachment.feedback, self.feedback)
        self.assertIsNotNone(attachment.image)
        self.assertEqual(attachment.caption, "Test image caption")
        self.assertIsNotNone(attachment.created_on)

    def test_create_attachment_without_caption(self):
        """Test creating an attachment without a caption (optional field)"""
        image = create_test_image()
        attachment = PluginVersionFeedbackAttachment.objects.create(
            feedback=self.feedback, image=image
        )

        self.assertIsNotNone(attachment.id)
        self.assertEqual(attachment.feedback, self.feedback)
        self.assertIsNotNone(attachment.image)
        self.assertIsNone(attachment.caption)

    def test_attachment_str_representation(self):
        """Test the string representation of the attachment"""
        image = create_test_image()
        attachment = PluginVersionFeedbackAttachment.objects.create(
            feedback=self.feedback, image=image, caption="Test caption"
        )

        expected_str = f"Attachment for {self.feedback}"
        self.assertEqual(str(attachment), expected_str)

    def test_attachment_related_to_feedback(self):
        """Test that attachments are properly related to feedback"""
        image1 = create_test_image("image1.png")
        image2 = create_test_image("image2.png")

        attachment1 = PluginVersionFeedbackAttachment.objects.create(
            feedback=self.feedback, image=image1, caption="First image"
        )
        attachment2 = PluginVersionFeedbackAttachment.objects.create(
            feedback=self.feedback, image=image2, caption="Second image"
        )

        # Check that feedback has both attachments
        attachments = self.feedback.attachments.all()
        self.assertEqual(attachments.count(), 2)
        self.assertIn(attachment1, attachments)
        self.assertIn(attachment2, attachments)

    def test_delete_attachment_deletes_image_file(self):
        """Test that deleting an attachment also deletes the image file"""
        image = create_test_image()
        attachment = PluginVersionFeedbackAttachment.objects.create(
            feedback=self.feedback, image=image, caption="Test image"
        )

        # Get the image path
        image_path = attachment.image.path

        # Delete the attachment
        attachment.delete()

        # Check that the image file is deleted
        self.assertFalse(os.path.exists(image_path))

    def test_multiple_attachments_for_different_feedbacks(self):
        """Test creating attachments for different feedbacks"""
        feedback2 = PluginVersionFeedback.objects.create(
            version=self.version, reviewer=self.staff, task="second feedback task"
        )

        image1 = create_test_image("image1.png")
        image2 = create_test_image("image2.png")

        attachment1 = PluginVersionFeedbackAttachment.objects.create(
            feedback=self.feedback, image=image1, caption="Attachment for feedback 1"
        )
        attachment2 = PluginVersionFeedbackAttachment.objects.create(
            feedback=feedback2, image=image2, caption="Attachment for feedback 2"
        )

        # Check that each feedback has its own attachment
        self.assertEqual(self.feedback.attachments.count(), 1)
        self.assertEqual(feedback2.attachments.count(), 1)
        self.assertEqual(self.feedback.attachments.first(), attachment1)
        self.assertEqual(feedback2.attachments.first(), attachment2)

    def test_cascade_delete_feedback_deletes_attachments(self):
        """Test that deleting feedback cascades to delete attachments"""
        image = create_test_image()
        attachment = PluginVersionFeedbackAttachment.objects.create(
            feedback=self.feedback, image=image, caption="Test image"
        )

        attachment_id = attachment.id

        # Delete the feedback
        self.feedback.delete()

        # Check that the attachment is also deleted
        self.assertFalse(
            PluginVersionFeedbackAttachment.objects.filter(id=attachment_id).exists()
        )

    def test_attachment_meta_verbose_names(self):
        """Test the verbose names of the attachment model"""
        self.assertEqual(
            PluginVersionFeedbackAttachment._meta.verbose_name,
            "Feedback Attachment",
        )
        self.assertEqual(
            PluginVersionFeedbackAttachment._meta.verbose_name_plural,
            "Feedback Attachments",
        )

    def test_attachment_created_on_auto_now_add(self):
        """Test that created_on is automatically set"""
        image = create_test_image()
        attachment = PluginVersionFeedbackAttachment.objects.create(
            feedback=self.feedback, image=image
        )

        self.assertIsNotNone(attachment.created_on)
        # created_on should not be editable
        self.assertFalse(
            PluginVersionFeedbackAttachment._meta.get_field("created_on").editable
        )

    def test_attachment_image_field_properties(self):
        """Test the properties of the image field"""
        image_field = PluginVersionFeedbackAttachment._meta.get_field("image")
        self.assertEqual(image_field.verbose_name, "Image")
        self.assertIsNotNone(image_field.help_text)

    def test_attachment_caption_field_properties(self):
        """Test the properties of the caption field"""
        caption_field = PluginVersionFeedbackAttachment._meta.get_field("caption")
        self.assertEqual(caption_field.verbose_name, "Caption")
        self.assertTrue(caption_field.blank)
        self.assertTrue(caption_field.null)
        self.assertEqual(caption_field.max_length, 255)


class FeedbackAttachmentIntegrationTest(TestCase):
    """Integration tests for feedback attachments with forms and views"""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.creator = User.objects.get(id=2)
        self.staff = User.objects.get(id=3)
        self.plugin = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-integration",
            name="test integration plugin",
            about="this is a test for integration",
        )
        self.version = PluginVersion.objects.create(
            plugin=self.plugin,
            created_by=self.creator,
            min_qg_version="0.0.0",
            max_qg_version="99.99.99",
            version="0.1",
            approved=False,
        )

    @patch("plugins.views.version_feedback_notify")
    def test_create_feedback_with_attachments_via_view(self, mock_notify):
        """Test creating feedback with attachments through the view"""
        self.client.force_login(self.staff)

        url = reverse(
            "version_feedback",
            args=[self.plugin.package_name, self.version.version],
        )

        # Create test images
        image1 = create_simple_test_image("test1.png")
        image2 = create_simple_test_image("test2.png")

        response = self.client.post(
            url,
            {
                "feedback": "- [ ] task 1\n- [ ] task 2",
                "images": [image1, image2],
            },
        )

        # Check redirect
        self.assertEqual(response.status_code, 302)

        # Check that feedbacks were created
        feedbacks = PluginVersionFeedback.objects.filter(version=self.version)
        self.assertEqual(feedbacks.count(), 2)

        # Check that attachments were created for the first feedback
        first_feedback = feedbacks.first()
        attachments = PluginVersionFeedbackAttachment.objects.filter(
            feedback=first_feedback
        )
        self.assertEqual(attachments.count(), 2)

        # Verify notify was called
        mock_notify.assert_called_once()

    @patch("plugins.views.version_feedback_notify")
    def test_create_feedback_without_attachments(self, mock_notify):
        """Test creating feedback without attachments"""
        self.client.force_login(self.staff)

        url = reverse(
            "version_feedback",
            args=[self.plugin.package_name, self.version.version],
        )

        response = self.client.post(
            url,
            {
                "feedback": "- [ ] task without images",
            },
        )

        # Check redirect
        self.assertEqual(response.status_code, 302)

        # Check that feedback was created
        feedbacks = PluginVersionFeedback.objects.filter(version=self.version)
        self.assertEqual(feedbacks.count(), 1)

        # Check that no attachments were created
        feedback = feedbacks.first()
        self.assertEqual(feedback.attachments.count(), 0)

    def test_view_feedback_with_attachments(self):
        """Test viewing feedback page with attachments"""
        self.client.force_login(self.staff)

        # Create feedback with attachments
        feedback = PluginVersionFeedback.objects.create(
            version=self.version, reviewer=self.staff, task="test task"
        )
        image = create_test_image()
        PluginVersionFeedbackAttachment.objects.create(
            feedback=feedback, image=image, caption="Test caption"
        )

        url = reverse(
            "version_feedback",
            args=[self.plugin.package_name, self.version.version],
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("feedbacks", response.context)
        feedbacks = response.context["feedbacks"]
        self.assertEqual(feedbacks.count(), 1)

        # Check that attachments are prefetched
        feedback = feedbacks.first()
        self.assertEqual(feedback.attachments.count(), 1)


class FeedbackAttachmentFormValidationTest(TestCase):
    """Test form validation for feedback attachments"""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        from plugins.forms import VersionFeedbackForm

        self.form_class = VersionFeedbackForm

    def test_form_accepts_valid_image(self):
        """Test that form accepts valid image files"""
        image = create_simple_test_image("valid.png")
        form = self.form_class(
            data={"feedback": "- [ ] test task"},
            files={"images": image},
        )
        self.assertTrue(form.is_valid())

    def test_form_accepts_multiple_images(self):
        """Test that form accepts multiple image files"""
        image1 = create_simple_test_image("valid1.png")
        image2 = create_simple_test_image("valid2.png")

        # Note: Testing multiple files with forms is tricky
        # This tests the clean_images method directly
        form = self.form_class(data={"feedback": "- [ ] test task"})
        form.cleaned_data = {"images": [image1, image2]}

        try:
            cleaned_images = form.clean_images()
            self.assertEqual(len(cleaned_images), 2)
        except Exception as e:
            self.fail(f"Form should accept multiple images: {e}")

    def test_form_rejects_non_image_file(self):
        """Test that form rejects non-image files"""
        text_file = SimpleUploadedFile(
            "test.txt", b"not an image", content_type="text/plain"
        )
        form = self.form_class(
            data={"feedback": "- [ ] test task"},
            files={"images": text_file},
        )

        # The form should be invalid
        self.assertFalse(form.is_valid())
        self.assertIn("images", form.errors)

    def test_form_rejects_oversized_image(self):
        """Test that form rejects images larger than 5MB"""
        # Create a large image (simulated)
        large_image = BytesIO()
        # Create a large enough image
        img = Image.new("RGB", (3000, 3000), color="red")
        img.save(large_image, format="PNG")
        large_image.seek(0)

        # Create file that exceeds 5MB
        large_file = InMemoryUploadedFile(
            large_image,
            "ImageField",
            "large.png",
            "image/png",
            6 * 1024 * 1024,  # 6MB
            None,
        )

        form = self.form_class(
            data={"feedback": "- [ ] test task"},
            files={"images": large_file},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("images", form.errors)

    def test_form_images_field_is_optional(self):
        """Test that images field is optional"""
        form = self.form_class(data={"feedback": "- [ ] test task without images"})
        self.assertTrue(form.is_valid())


class FeedbackAttachmentQueryTest(TestCase):
    """Test querying attachments"""

    fixtures = ["fixtures/auth.json"]

    def setUp(self):
        self.creator = User.objects.get(id=2)
        self.staff = User.objects.get(id=3)
        self.plugin = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-query",
            name="test query plugin",
            about="this is a test for querying attachments",
        )
        self.version = PluginVersion.objects.create(
            plugin=self.plugin,
            created_by=self.creator,
            min_qg_version="0.0.0",
            max_qg_version="99.99.99",
            version="0.1",
            approved=False,
        )

    def test_query_attachments_by_feedback(self):
        """Test querying attachments by feedback"""
        feedback = PluginVersionFeedback.objects.create(
            version=self.version, reviewer=self.staff, task="test task"
        )

        image1 = create_test_image("image1.png")
        image2 = create_test_image("image2.png")

        PluginVersionFeedbackAttachment.objects.create(
            feedback=feedback, image=image1, caption="Image 1"
        )
        PluginVersionFeedbackAttachment.objects.create(
            feedback=feedback, image=image2, caption="Image 2"
        )

        attachments = PluginVersionFeedbackAttachment.objects.filter(feedback=feedback)
        self.assertEqual(attachments.count(), 2)

    def test_query_attachments_by_version(self):
        """Test querying attachments through version relationship"""
        feedback1 = PluginVersionFeedback.objects.create(
            version=self.version, reviewer=self.staff, task="task 1"
        )
        feedback2 = PluginVersionFeedback.objects.create(
            version=self.version, reviewer=self.staff, task="task 2"
        )

        image1 = create_test_image("image1.png")
        image2 = create_test_image("image2.png")

        PluginVersionFeedbackAttachment.objects.create(feedback=feedback1, image=image1)
        PluginVersionFeedbackAttachment.objects.create(feedback=feedback2, image=image2)

        # Query attachments through version
        attachments = PluginVersionFeedbackAttachment.objects.filter(
            feedback__version=self.version
        )
        self.assertEqual(attachments.count(), 2)

    def test_prefetch_attachments_with_feedback(self):
        """Test prefetching attachments when querying feedbacks"""
        feedback = PluginVersionFeedback.objects.create(
            version=self.version, reviewer=self.staff, task="test task"
        )

        image = create_test_image()
        PluginVersionFeedbackAttachment.objects.create(feedback=feedback, image=image)

        # Query with prefetch
        feedbacks = PluginVersionFeedback.objects.filter(
            version=self.version
        ).prefetch_related("attachments")

        feedback = feedbacks.first()
        # This should not trigger additional queries
        attachments = feedback.attachments.all()
        self.assertEqual(attachments.count(), 1)

    def test_order_attachments_by_created_on(self):
        """Test ordering attachments by creation date"""
        feedback = PluginVersionFeedback.objects.create(
            version=self.version, reviewer=self.staff, task="test task"
        )

        image1 = create_test_image("image1.png")
        image2 = create_test_image("image2.png")
        image3 = create_test_image("image3.png")

        attachment1 = PluginVersionFeedbackAttachment.objects.create(
            feedback=feedback, image=image1, caption="First"
        )
        attachment2 = PluginVersionFeedbackAttachment.objects.create(
            feedback=feedback, image=image2, caption="Second"
        )
        attachment3 = PluginVersionFeedbackAttachment.objects.create(
            feedback=feedback, image=image3, caption="Third"
        )

        # Query ordered by created_on
        attachments = PluginVersionFeedbackAttachment.objects.filter(
            feedback=feedback
        ).order_by("created_on")

        self.assertEqual(list(attachments), [attachment1, attachment2, attachment3])
