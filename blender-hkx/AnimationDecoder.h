#pragma once
#include "common.h"

namespace iohkx
{
	class AnimationDecoder
	{
	public:
		AnimationDecoder();
		~AnimationDecoder();

		hkRefPtr<hkaAnimationContainer> compress();
		void decompress(hkaAnimationContainer* animCtnr, 
			const std::vector<Skeleton*>& skeletons);

		AnimationData& get() { return m_data; }
		const AnimationData& get() const { return m_data; }

		void setFrameRate(int frameRate) { m_frameRate = frameRate; }
		int getFrameRate() const { return m_frameRate; }

	private:
		void removeDuplicateKeys();
		void preProcess();

	private:
		AnimationData m_data;
		int m_frameRate;
	};
}
