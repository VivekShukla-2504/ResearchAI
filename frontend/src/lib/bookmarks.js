export async function requestBookmarkChange({ paper, isSaved, client }) {
  try {
    if (isSaved) {
      const result = await client.removeBookmark(paper.paper_id)
      if (typeof result?.deleted !== 'boolean') {
        throw new Error('The API did not confirm that this bookmark was removed.')
      }
      return {
        status: 'success',
        action: 'remove',
        message: result.deleted === false ? 'Bookmark was already removed' : 'Bookmark removed',
      }
    }

    const bookmark = await client.addBookmark(paper.paper_id)
    if (!bookmark || bookmark.paper_id !== paper.paper_id) {
      throw new Error('The API did not confirm that this paper was saved.')
    }
    return { status: 'success', action: 'save', bookmark, message: 'Paper saved to bookmarks' }
  } catch (error) {
    return {
      status: 'error',
      action: 'none',
      error,
      message: error?.message || 'Could not update this bookmark. Please try again.',
    }
  }
}
